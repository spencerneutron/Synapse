#!/usr/bin/env python3
"""
extract.py — chunk, embed, and store session archive content and vault notes.

Subcommands:
  init                       Create DB schema if missing.
  embed-archive <session-id> Embed PLAN/EXECUTION/NOTES files for one session.
  embed-note <path>          Embed a single vault note (decision/pattern/session).
  status <session-id>        Report extraction status for a session.
  upgrade                    Bring the DB to the current schema (backs up first,
                             keeps every vector; also creates a new DB).
  supersede <old> --by <new> Mark a Decision note superseded in the DB and in its
                             front matter; recall then hides it by default.
  reembed-all                Detect embedding-model mismatches and re-embed.

The script is deterministic and idempotent. Atomic-note extraction (deciding
what becomes a Decision or Pattern note) is the skill's job, not this script's.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# ---------- venv bootstrap ----------
# A system Python (e.g. Homebrew's, which is externally managed under PEP 668)
# usually does not carry sqlite-vec. `synapse setup` keeps it in a venv under
# the Synapse home (paths.venv_dir()). If the current interpreter can't import
# sqlite_vec, re-exec under the venv interpreter so callers don't have to know
# which python to use. Every module that needs the DB imports this one, so all
# of them inherit the fix.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402


def _reexec_under_venv_if_needed() -> None:
    import importlib.util

    if importlib.util.find_spec("sqlite_vec") is not None:
        return  # current interpreter already has it — nothing to do
    if os.environ.get("SYNAPSE_VENV_REEXEC") == "1":
        return  # already re-exec'd once; fall through to the clear error path

    venv_python = paths.venv_python()

    # No venv to fall back to: let the normal "sqlite-vec not installed" error
    # in db_connect() speak for itself. We deliberately do NOT compare
    # sys.executable to the venv python — a venv interpreter is a symlink to the
    # same base binary, so the two resolve() identically and the comparison
    # always misfires. The find_spec check above already proves this interpreter
    # lacks sqlite-vec, and the SYNAPSE_VENV_REEXEC sentinel stops an infinite loop
    # if the venv somehow lacks it too.
    if not venv_python.exists():
        return

    os.environ["SYNAPSE_VENV_REEXEC"] = "1"
    if os.environ.get("SYNAPSE_OPTIONAL"):
        # An optional hook (recall hint) must fail open even when the venv's
        # interpreter cannot start (e.g. its base Python was upgraded away):
        # run it as a child, drop its stderr, and always exit 0.
        import subprocess
        subprocess.run([str(venv_python), *sys.argv], stderr=subprocess.DEVNULL)
        sys.exit(0)
    if sys.platform == "win32":
        # Windows has no real exec: os.execv spawns a child and exits at once,
        # so the shell loses the child's output and exit code. Wait for it.
        import subprocess
        sys.exit(subprocess.run([str(venv_python), *sys.argv]).returncode)
    os.execv(str(venv_python), [str(venv_python), *sys.argv])


_reexec_under_venv_if_needed()

# Force UTF-8 for stdout/stderr. Windows PowerShell defaults to cp1252,
# which mangles em-dashes and other unicode coming from archive content.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ---------- Configuration ----------

EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768
OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_TIMEOUT_S = 30           # the recall hint lowers this to fit its hook budget

# Chunking targets. Tokens are approximated as words * 1.3 — close enough
# for boundary decisions; the embedding model has its own tokenizer.
CHUNK_TARGET_WORDS = 500       # ~650 tokens
CHUNK_MAX_WORDS = 800          # ~1000 tokens, hard ceiling
CHUNK_MIN_WORDS = 30           # below this, merge with neighbor



# ---------- Data types ----------

@dataclass
class Chunk:
    """A unit of text destined for embedding."""
    text: str                  # the chunk content, with breadcrumb prepended
    source_path: str           # relative path to source file
    source_type: str           # 'session' | 'decision' | 'pattern' | 'archive'
    session_id: str | None
    project: str | None
    chunk_index: int
    metadata: dict             # heading breadcrumb, frontmatter, etc.

    def hash(self) -> str:
        """Stable identity. Same source + position + text => same hash."""
        h = hashlib.sha256()
        h.update(self.source_path.encode())
        h.update(str(self.chunk_index).encode())
        h.update(self.text.encode())
        return h.hexdigest()


# ---------- DB layer ----------

def db_connect(db_path: Path) -> sqlite3.Connection:
    """Open DB and load sqlite-vec extension. Handles Windows DLL search-path
    quirks and detects Python builds without extension-loading support."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)

    # Some Python distributions (notably older python.org Windows builds)
    # ship sqlite3 without extension-loading compiled in.
    if not hasattr(conn, "enable_load_extension"):
        sys.exit(
            "error: this Python's sqlite3 module was built without "
            "extension-loading support.\n"
            "fix: pip install pysqlite3-binary, then change the import in "
            "this script from 'import sqlite3' to "
            "'import pysqlite3 as sqlite3'."
        )

    try:
        import sqlite_vec
    except ImportError:
        sys.exit("error: sqlite-vec not installed. run: synapse setup")

    conn.enable_load_extension(True)

    ext_path = sqlite_vec.loadable_path()

    # On Windows, the bundled vec0.dll has dependencies that the OS resolves
    # via the standard DLL search path. Python 3.8+ requires explicit
    # os.add_dll_directory() for directories outside that path.
    if sys.platform == "win32":
        ext_dir = os.path.dirname(ext_path)
        if hasattr(os, "add_dll_directory") and os.path.isdir(ext_dir):
            try:
                os.add_dll_directory(ext_dir)
            except (OSError, FileNotFoundError):
                pass  # fall through to load_extension and let it error clearly

    try:
        conn.load_extension(ext_path)
    except sqlite3.OperationalError as e:
        hint = ""
        if sys.platform == "win32":
            hint = (
                "\nWindows hint: ensure you're running this from a non-elevated "
                "shell, and that the vec0.dll file exists at:\n"
                f"  {ext_path}.dll"
            )
        sys.exit(f"error: failed to load sqlite-vec extension: {e}{hint}")

    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    # SQLite's lower() folds ASCII only; recall's keyword filter uses this
    # instead, so it matches the Python-lowered project partition in chunks_vec.
    conn.create_function("py_lower", 1, lambda s: s.lower() if isinstance(s, str) else s,
                         deterministic=True)
    return conn


SCHEMA_VERSION = 2

CHUNKS_DDL = """
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY,
        chunk_hash TEXT UNIQUE NOT NULL,
        source_path TEXT NOT NULL,
        source_type TEXT NOT NULL,
        session_id TEXT,
        project TEXT,
        chunk_index INTEGER NOT NULL,
        text TEXT NOT NULL,
        metadata JSON,
        embedding_model TEXT NOT NULL,
        embedding_dim INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        superseded_by TEXT,
        origin TEXT,
        author TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_chunks_session ON chunks(session_id);
    CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project);
    CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(source_type);
    CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_path);
"""

# Filters run inside the KNN search on these metadata columns. project is a
# partition key, lower-cased so a project filter ignores case ("VeilMX" and
# "veilmx" are one project). origin and author are reserved for shared stores.
VEC_DDL = f"""
    CREATE VIRTUAL TABLE chunks_vec USING vec0(
        embedding FLOAT[{EMBEDDING_DIM}] distance_metric=cosine,
        project TEXT PARTITION KEY,
        source_type TEXT,
        status TEXT
    );
"""
FTS_DDL = "CREATE VIRTUAL TABLE chunks_fts USING fts5(text, tokenize='porter unicode61');"
META_DDL = "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"


def vec_project(project: str | None) -> str:
    """The partition value stored for a project: lower-cased, never NULL."""
    return (project or "").lower()


def schema_version(conn: sqlite3.Connection) -> int:
    """0 = empty DB, 1 = the V1/v1.6 layout, 2 = current."""
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "meta" in tables:
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row:
            return int(row[0])
    return 1 if "chunks" in tables else 0


def require_current(conn: sqlite3.Connection, db_path: Path) -> None:
    v = schema_version(conn)
    if v > SCHEMA_VERSION:
        sys.exit(f"error: {db_path} uses schema v{v}, newer than this plugin understands "
                 f"(v{SCHEMA_VERSION}); update Synapse (claude plugin update synapse@synapse)")
    if v not in (0, SCHEMA_VERSION):
        sys.exit(f"error: {db_path} uses schema v{v}; run `synapse extract upgrade` "
                 f"(or `synapse setup`). It backs the DB up first and keeps every vector.")


def db_init(conn: sqlite3.Connection, db_path: Path | None = None) -> None:
    """Create the current schema on an empty DB. Safe to call repeatedly;
    refuses to touch an older schema (that is `upgrade`'s job)."""
    v = schema_version(conn)
    if v == SCHEMA_VERSION:
        return
    if v != 0:
        require_current(conn, db_path or Path("vectors.db"))
    conn.executescript(CHUNKS_DDL + VEC_DDL + FTS_DDL + META_DDL)
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                 (str(SCHEMA_VERSION),))
    conn.commit()


def insert_chunk(conn: sqlite3.Connection, row: dict, embedding) -> int:
    """Insert one chunk with its vector and full-text entry. `embedding` is a
    JSON array string or sqlite-vec's float32 blob. Returns the chunk id."""
    status = row.get("status") or "active"
    cur = conn.execute(
        """INSERT INTO chunks (chunk_hash, source_path, source_type, session_id, project,
               chunk_index, text, metadata, embedding_model, embedding_dim, created_at,
               status, superseded_by, origin, author)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (row["chunk_hash"], row["source_path"], row["source_type"], row.get("session_id"),
         row.get("project"), row["chunk_index"], row["text"], row.get("metadata"),
         row["embedding_model"], row["embedding_dim"], row["created_at"],
         status, row.get("superseded_by"), row.get("origin"), row.get("author")),
    )
    cid = cur.lastrowid
    conn.execute(
        "INSERT INTO chunks_vec (rowid, embedding, project, source_type, status) VALUES (?, ?, ?, ?, ?)",
        (cid, embedding, vec_project(row.get("project")), row["source_type"], status),
    )
    conn.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (cid, row["text"]))
    return cid


def delete_chunks(conn: sqlite3.Connection, ids: list[int]) -> None:
    if not ids:
        return
    marks = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM chunks_vec WHERE rowid IN ({marks})", ids)
    conn.execute(f"DELETE FROM chunks_fts WHERE rowid IN ({marks})", ids)
    conn.execute(f"DELETE FROM chunks WHERE id IN ({marks})", ids)


# ---------- Embedding ----------

def embed_text(text: str, input_type: str = "document") -> list[float]:
    """Call Ollama for a single embedding. Raises on failure.

    nomic-embed-text was trained with task-specific prefixes and expects them.
    Documents (stored content) get 'search_document:'; queries get
    'search_query:'. Mixing or omitting these degrades recall quality.
    """
    if input_type == "document":
        prefixed = f"search_document: {text}"
    elif input_type == "query":
        prefixed = f"search_query: {text}"
    else:
        raise ValueError(f"input_type must be 'document' or 'query', got {input_type!r}")

    payload = json.dumps({"model": EMBEDDING_MODEL, "prompt": prefixed}).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=EMBED_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        sys.exit(
            f"error: cannot reach Ollama at {OLLAMA_URL} ({e.reason}).\n"
            "is `ollama serve` running? is the model pulled "
            f"(`ollama pull {EMBEDDING_MODEL}`)?"
        )
    embedding = data.get("embedding")
    if not embedding or len(embedding) != EMBEDDING_DIM:
        sys.exit(
            f"error: unexpected embedding shape from Ollama: "
            f"got {len(embedding) if embedding else 0} dims, expected {EMBEDDING_DIM}"
        )
    return embedding


def embed_batch(texts: list[str], input_type: str = "document") -> list[list[float]]:
    """Embed a list of texts. Ollama doesn't batch, so we loop."""
    return [embed_text(t, input_type=input_type) for t in texts]


# ---------- Chunking ----------

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter (returned as dict) and body. Naive parser —
    handles flat key:value pairs, which is all our schemas use."""
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    fm_text = m.group(1)
    body = content[m.end():]
    fm = {}
    for line in fm_text.splitlines():
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def split_by_headings(body: str) -> list[tuple[list[str], str]]:
    """Split markdown body into (heading_path, section_text) tuples.

    heading_path is the chain of headings leading to this section, e.g.
    ['Session 2026-04-23', 'Decision Log', 'Use sqlite-vec'].
    """
    lines = body.splitlines(keepends=True)
    sections: list[tuple[list[str], str]] = []
    current_path: list[str] = []
    current_text: list[str] = []

    def flush():
        if current_text:
            text = "".join(current_text).strip()
            if text:
                sections.append((list(current_path), text))

    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            flush()
            current_text = []
            level = len(m.group(1))
            title = m.group(2).strip()
            current_path = current_path[: level - 1]
            while len(current_path) < level - 1:
                current_path.append("")
            current_path.append(title)
        else:
            current_text.append(line)
    flush()
    return sections


# Patterns for detecting chunks that contain no semantic information.
# These chunks are technically text but tell us nothing about the session.

# Empty markers: explicit "nothing here" statements, possibly wrapped in
# emphasis or backticks. Must match the WHOLE body after stripping.
# Catches: "None.", "N/A", "TBD", "_None._", "(none)", "no open items",
# "no open items — session closed clean", etc.
EMPTY_MARKER_RE = re.compile(
    r"^[_*`\s.()\-—–]*"
    r"(?:"
    r"none|n/?a|tbd|nothing|empty"
    r"|no\s+(?:open\s+)?\w+(?:\s+[—–-]\s+session\s+closed\s+clean)?"
    r")"
    r"[_*`\s.()\-—–]*$",
    re.IGNORECASE,
)

# A chunk that is purely punctuation, dashes, or formatting characters.
PUNCT_ONLY_RE = re.compile(r"^[\s\-—–_*`.()|]+$")

# Key-value metadata line. Handles both:
#   **Key:** value   (colon inside the bold)
#   **Key**: value   (colon outside the bold)
METADATA_LINE_PREFIX_RE = re.compile(
    r"^\s*\*\*[^*]+?(?::\*\*|\*\*\s*:)\s*"
)


def is_metadata_line(line: str) -> bool:
    """A line is metadata-only if it starts with **Key:** and what follows
    the prefix is a short value (path, date, link), not full prose."""
    m = METADATA_LINE_PREFIX_RE.match(line)
    if not m:
        return False
    remainder = line[m.end():].strip()
    # A short remainder (<8 meaningful words) is a value, not a sentence.
    return meaningful_word_count(remainder) < 8


# Pure markdown link reference: -? `path` or -? [text](url) with no prose.
# Also catches "Word: `path`" style lines like "Archive: `path/to/file.md`".
REFERENCE_LINE_RE = re.compile(
    r"^\s*[-*]?\s*"
    r"(?:`[^`]+`|\[[^\]]+\]\([^)]+\)|[A-Za-z][A-Za-z\s]*:\s*`[^`]+`)"
    r"\s*$"
)

# Markdown formatting-only lines: horizontal rules (---, ***, ___),
# blank-equivalent decorative lines. These carry no information and
# shouldn't prevent a chunk from being recognized as low-info.
FORMATTING_LINE_RE = re.compile(r"^[\s\-—–_*=]+$")


def meaningful_word_count(text: str) -> int:
    """Count words that aren't pure punctuation, formatting, or single chars."""
    count = 0
    for word in text.split():
        # Strip surrounding markdown / punctuation
        stripped = word.strip("_*`-.,;:()[]{}\"'")
        if len(stripped) >= 2 and any(c.isalnum() for c in stripped):
            count += 1
    return count


def is_low_information(body: str) -> bool:
    """Return True if this chunk has no useful semantic content.

    Conservative: only drops chunks that are short AND match a known
    "no information" pattern. Anything 15+ meaningful words is kept,
    even if it looks metadata-heavy."""
    stripped = body.strip()
    if not stripped:
        return True

    # Pure punctuation/dashes — drop regardless of length.
    if PUNCT_ONLY_RE.match(stripped):
        return True

    if meaningful_word_count(stripped) >= 15:
        return False

    # Empty marker: the whole body is a "nothing here" statement.
    if EMPTY_MARKER_RE.match(stripped):
        return True

    # Pure metadata, references, or decorative formatting: every non-empty
    # line matches one of the known noise patterns.
    non_empty_lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    if non_empty_lines and all(
        is_metadata_line(ln)
        or REFERENCE_LINE_RE.match(ln)
        or FORMATTING_LINE_RE.match(ln)
        for ln in non_empty_lines
    ):
        return True

    return False


def split_long_section(text: str) -> list[str]:
    """Split a section that exceeds CHUNK_MAX_WORDS at paragraph boundaries.
    Falls back to sentence splits if a single paragraph is still too long."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buffer: list[str] = []
    buffer_words = 0

    def flush_buffer():
        nonlocal buffer, buffer_words
        if buffer:
            chunks.append("\n\n".join(buffer))
            buffer = []
            buffer_words = 0

    for para in paragraphs:
        para_words = len(para.split())
        if para_words > CHUNK_MAX_WORDS:
            # paragraph itself too long; split by sentence
            flush_buffer()
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sent_buf: list[str] = []
            sent_words = 0
            for s in sentences:
                sw = len(s.split())
                if sent_words + sw > CHUNK_TARGET_WORDS and sent_buf:
                    chunks.append(" ".join(sent_buf))
                    sent_buf = []
                    sent_words = 0
                sent_buf.append(s)
                sent_words += sw
            if sent_buf:
                chunks.append(" ".join(sent_buf))
        elif buffer_words + para_words > CHUNK_TARGET_WORDS and buffer:
            flush_buffer()
            buffer.append(para)
            buffer_words = para_words
        else:
            buffer.append(para)
            buffer_words += para_words
    flush_buffer()
    return chunks


def chunk_document(
    content: str,
    source_path: str,
    source_type: str,
    session_id: str | None,
    project: str | None,
) -> list[Chunk]:
    """Turn a markdown document into chunks ready for embedding.

    Strategy:
      1. Strip frontmatter (kept in metadata).
      2. Split by H2/H3 headings into sections.
      3. For each section, split further if it exceeds CHUNK_MAX_WORDS.
      4. Merge tiny sections with their predecessor.
      5. Prepend a breadcrumb to each chunk's text for retrieval clarity.
    """
    frontmatter, body = parse_frontmatter(content)
    sections = split_by_headings(body)

    if not sections:
        # no headings — treat the whole body as one section
        sections = [([], body.strip())] if body.strip() else []

    chunks: list[Chunk] = []
    chunk_idx = 0

    for heading_path, section_text in sections:
        word_count = len(section_text.split())
        if word_count == 0:
            continue

        if word_count > CHUNK_MAX_WORDS:
            pieces = split_long_section(section_text)
        else:
            pieces = [section_text]

        # Skip H1 in breadcrumb — it's always redundant with the filename
        # for our schemas (session notes, decision notes, pattern notes all
        # have an H1 that mirrors their identity).
        breadcrumb_path = [h for h in heading_path[1:] if h]
        breadcrumb_parts = [Path(source_path).stem] + breadcrumb_path
        breadcrumb = " > ".join(breadcrumb_parts)

        for piece in pieces:
            # Drop chunks with no semantic information (empty markers,
            # pure metadata, pure link references). See is_low_information.
            if is_low_information(piece):
                continue

            # Only merge a tiny chunk into its predecessor if they share
            # the same parent heading. Cross-heading merges destroy the
            # breadcrumb's signal value for retrieval.
            if (
                len(piece.split()) < CHUNK_MIN_WORDS
                and chunks
                and chunks[-1].metadata.get("heading_path") == heading_path
            ):
                prev = chunks[-1]
                prev.text = f"{prev.text}\n\n{piece}"
                continue

            chunk_text = f"[{breadcrumb}]\n{piece}"

            chunks.append(Chunk(
                text=chunk_text,
                source_path=source_path,
                source_type=source_type,
                session_id=session_id,
                project=project,
                chunk_index=chunk_idx,
                metadata={
                    "breadcrumb": breadcrumb,
                    "heading_path": heading_path,
                    "frontmatter": frontmatter,
                },
            ))
            chunk_idx += 1

    return chunks


# ---------- Storage ----------

def store_chunks(conn: sqlite3.Connection, chunks: list[Chunk], status: str = "active",
                 superseded_by: str | None = None, origin: str | None = None,
                 author: str | None = None) -> tuple[int, int]:
    """Embed and insert chunks. Returns (inserted, skipped) counts. origin and
    author mark a team's notes (None for the personal store)."""
    if not chunks:
        return 0, 0

    inserted = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()

    embeddings = embed_batch([c.text for c in chunks])

    for chunk, emb in zip(chunks, embeddings):
        chunk_hash = chunk.hash()

        # Idempotency: skip if hash already present.
        existing = conn.execute(
            "SELECT id FROM chunks WHERE chunk_hash = ?",
            (chunk_hash,),
        ).fetchone()
        if existing:
            skipped += 1
            continue

        insert_chunk(conn, {
            "chunk_hash": chunk_hash, "source_path": chunk.source_path,
            "source_type": chunk.source_type, "session_id": chunk.session_id,
            "project": chunk.project, "chunk_index": chunk.chunk_index,
            "text": chunk.text, "metadata": json.dumps(chunk.metadata),
            "embedding_model": EMBEDDING_MODEL, "embedding_dim": EMBEDDING_DIM,
            "created_at": now, "status": status, "superseded_by": superseded_by,
            "origin": origin, "author": author,
        }, json.dumps(emb))
        inserted += 1

    conn.commit()
    return inserted, skipped


# ---------- Subcommands ----------

def cmd_init(args: argparse.Namespace) -> int:
    conn = db_connect(args.db)
    db_init(conn, args.db)
    print(f"initialized {args.db}")
    return 0


def cmd_embed_archive(args: argparse.Namespace) -> int:
    r = paths.resolve(project=args.project)
    archive_dir = Path(args.archive_dir) if args.archive_dir else r.archive_dir
    processed_dir = Path(args.processed_dir) if args.processed_dir else r.processed_dir
    session_id = args.session_id
    project = r.project

    # Standard archive set is always considered. REPORT is opt-in via flag
    # because REPORT files are emergent session deliverables that may quote
    # code or external data heavily — useful when present and wanted, but
    # not always part of the knowledge-worth content we want in recall.
    prefixes = ["PLAN", "EXECUTION", "NOTES"]
    if args.include_report:
        prefixes.append("REPORT")

    files_to_embed = []
    for prefix in prefixes:
        path = archive_dir / f"{prefix}_{session_id}.md"
        if path.exists():
            files_to_embed.append(path)

    if not files_to_embed:
        sys.exit(f"error: no archive files found for session {session_id} in {archive_dir}")

    conn = db_connect(args.db)
    db_init(conn, args.db)

    if args.force:
        # Delete existing chunks for this session so re-ingest produces
        # fresh vectors. Use a transaction so chunks and vectors stay in sync.
        deleted = conn.execute(
            "SELECT id FROM chunks WHERE session_id = ?", (session_id,)
        ).fetchall()
        if deleted:
            ids = [row["id"] for row in deleted]
            delete_chunks(conn, ids)
            conn.commit()
            print(f"  --force: cleared {len(ids)} existing chunks for session {session_id}")

    total_inserted = 0
    total_skipped = 0

    for path in files_to_embed:
        content = path.read_text(encoding="utf-8")
        chunks = chunk_document(
            content=content,
            source_path=paths.to_stored_path(path, r),
            source_type="archive",
            session_id=session_id,
            project=project,
        )
        inserted, skipped = store_chunks(conn, chunks)
        total_inserted += inserted
        total_skipped += skipped
        print(f"  {path.name}: {inserted} new, {skipped} unchanged")

    # Write processed marker.
    processed_dir.mkdir(parents=True, exist_ok=True)
    marker = processed_dir / f"{session_id}.json"
    marker.write_text(json.dumps({
        "session_id": session_id,
        "project": project,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": EMBEDDING_MODEL,
        "files": [paths.to_stored_path(p, r) for p in files_to_embed],
        "chunks_inserted": total_inserted,
        "chunks_skipped": total_skipped,
    }, indent=2), encoding="utf-8")

    print(f"session {session_id}: {total_inserted} chunks embedded, "
          f"{total_skipped} already present")
    return 0


def cmd_embed_note(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        sys.exit(f"error: {path} not found")

    content = path.read_text(encoding="utf-8")
    frontmatter, _ = parse_frontmatter(content)
    source_type = frontmatter.get("type", "note")
    session_id = frontmatter.get("session_id") or None
    r = paths.resolve(project=frontmatter.get("project") or args.project)
    project = r.project
    # A superseded note keeps that status when it is re-embedded.
    status = "superseded" if str(frontmatter.get("status", "")).strip() == "superseded" else "active"
    superseded_by = frontmatter.get("superseded_by") or None
    if superseded_by:  # front matter holds a [[wikilink]]; the DB holds the stored path
        superseded_by = note_ref(str(superseded_by), r, path.parent.name)[0]

    conn = db_connect(args.db)
    db_init(conn, args.db)

    # Always-replace semantics: vault notes can be edited (manually or by
    # re-extraction). Delete any existing chunks for this exact source_path
    # before re-inserting. Without this, edited content produces duplicate
    # chunks (old + new versions both present in the DB), which corrupts
    # recall results. There's no `--force` flag for this command — replacement
    # is the only correct behavior for note re-embedding.
    source_path_str = paths.to_stored_path(path, r)
    existing = conn.execute(
        "SELECT id, status, superseded_by FROM chunks WHERE source_path = ?", (source_path_str,)
    ).fetchall()
    # The DB is the authority on supersession: if the note was superseded but
    # its front matter could not be updated, a re-embed must not revive it.
    was = next((row for row in existing if row["status"] == "superseded"), None)
    if was and status != "superseded":
        status, superseded_by = "superseded", was["superseded_by"]
        print(f"  {path.name} stays superseded (by {superseded_by})")
    if existing:
        ids = [row["id"] for row in existing]
        delete_chunks(conn, ids)
        conn.commit()
        print(f"  cleared {len(ids)} existing chunks for {path.name}")

    chunks = chunk_document(
        content=content,
        source_path=source_path_str,
        source_type=source_type,
        session_id=session_id,
        project=project,
    )
    inserted, skipped = store_chunks(conn, chunks, status=status, superseded_by=superseded_by)
    print(f"{path.name}: {inserted} new, {skipped} unchanged"
          + (" (superseded)" if status == "superseded" else ""))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    r = paths.resolve(project=args.project)
    processed_dir = Path(args.processed_dir) if args.processed_dir else r.processed_dir
    marker = processed_dir / f"{args.session_id}.json"
    if not marker.exists():
        print(f"session {args.session_id}: not processed")
        return 1
    print(marker.read_text())
    return 0


def cmd_reembed_all(args: argparse.Namespace) -> int:
    conn = db_connect(args.db)
    rows = conn.execute(
        "SELECT DISTINCT embedding_model FROM chunks"
    ).fetchall()
    models = [r["embedding_model"] for r in rows]
    if not models:
        print("no chunks in db")
        return 0
    if models == [EMBEDDING_MODEL]:
        print(f"all chunks use current model ({EMBEDDING_MODEL}); nothing to do")
        return 0
    print(f"found chunks from models: {models}; current is {EMBEDDING_MODEL}")
    print("re-embed not yet implemented — flagged as a v2 feature")
    return 2


def cmd_upgrade(args: argparse.Namespace) -> int:
    """v1 -> v2 in place: back up, rebuild chunks_vec with filter metadata from
    the stored vectors (no re-embedding), build the full-text index, verify."""
    db = Path(args.db)
    conn = db_connect(db)
    v = schema_version(conn)
    if v == SCHEMA_VERSION:
        print(f"{db}: already schema v{SCHEMA_VERSION}")
        return 0
    if v > SCHEMA_VERSION:
        require_current(conn, db)  # exits: newer than this plugin
    if v == 0:
        db_init(conn, db)
        print(f"{db}: created schema v{SCHEMA_VERSION}")
        return 0

    rows = conn.execute(
        "SELECT c.id, c.project, c.source_type, c.text, v.embedding "
        "FROM chunks c JOIN chunks_vec v ON v.rowid = c.id").fetchall()
    total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    if len(rows) != total:
        sys.exit(f"error: {total - len(rows)} chunk(s) have no vector; nothing changed")
    vectors = {r["id"]: bytes(r["embedding"]) for r in rows}

    backup = db.with_name(f"{db.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    b = sqlite3.connect(backup)
    conn.backup(b)
    b.close()
    print(f"  backup: {backup}")

    conn.isolation_level = None  # manage the transaction by hand, DDL included
    try:
        conn.execute("BEGIN")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(chunks)")}
        for col, ddl in (("status", "TEXT NOT NULL DEFAULT 'active'"), ("superseded_by", "TEXT"),
                         ("origin", "TEXT"), ("author", "TEXT")):
            if col not in cols:
                conn.execute(f"ALTER TABLE chunks ADD COLUMN {col} {ddl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_path)")
        conn.execute("DROP TABLE chunks_vec")
        conn.execute(VEC_DDL)
        conn.execute(FTS_DDL)
        for r in rows:
            conn.execute(
                "INSERT INTO chunks_vec (rowid, embedding, project, source_type, status) "
                "VALUES (?, ?, ?, ?, 'active')",
                (r["id"], vectors[r["id"]], vec_project(r["project"]), r["source_type"]))
            conn.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (r["id"], r["text"]))
        conn.execute(META_DDL)
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                     (str(SCHEMA_VERSION),))
        conn.execute("COMMIT")
    except sqlite3.Error as e:
        conn.execute("ROLLBACK")
        sys.exit(f"error: upgrade failed ({e}); the DB is unchanged and a backup is at {backup}")
    finally:
        conn.isolation_level = ""

    counts = [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("chunks", "chunks_vec", "chunks_fts")]
    changed = sum(1 for rid, emb in conn.execute("SELECT rowid, embedding FROM chunks_vec")
                  if bytes(emb) != vectors.get(rid))
    if len(set(counts)) != 1 or changed:
        sys.exit(f"error: verification failed (chunks/vectors/text = {counts}, "
                 f"{changed} vector(s) changed); restore {backup}")
    print(f"{db}: upgraded to schema v{SCHEMA_VERSION}; {counts[0]} chunks, "
          f"every vector unchanged")
    return 0


def note_ref(arg: str, r: "paths.Resolved", folder: str) -> tuple[str, Path | None]:
    """A note given as a path, a [[wikilink]], or a title -> (stored path, file or None)."""
    if arg.endswith(".md") and ("/" in arg or "\\" in arg):
        p = Path(arg).expanduser()
        stored = paths.to_stored_path(p, r)
        if p.is_absolute():
            return stored, p
        if stored.startswith("vault/") and r.vault_path:
            return stored, r.vault_path / stored.removeprefix("vault/")
        return stored, None
    import vault_write
    title = arg.strip().removeprefix("[[").removesuffix("]]")
    title = re.split(r"[|#]", title, maxsplit=1)[0].strip()   # [[Title|alias]], [[Title#Heading]]
    title = re.sub(r"^(Decision|Pattern):\s*", "", title).removesuffix(".md")
    name = vault_write.safe_name(title)
    stored = f"vault/{folder}/{name}.md"
    return stored, (r.vault_path / folder / f"{name}.md") if r.vault_path else None


def cmd_supersede(args: argparse.Namespace) -> int:
    r = paths.resolve()
    old, old_file = note_ref(args.old, r, args.folder)
    new, _ = note_ref(args.by, r, args.folder)
    if old == new:
        sys.exit("error: a note cannot supersede itself")

    conn = db_connect(args.db)
    require_current(conn, args.db)
    ids = [row["id"] for row in conn.execute("SELECT id FROM chunks WHERE source_path = ?", (old,))]
    for cid in ids:
        conn.execute("UPDATE chunks SET status = 'superseded', superseded_by = ? WHERE id = ?", (new, cid))
        conn.execute("UPDATE chunks_vec SET status = 'superseded' WHERE rowid = ?", (cid,))
    conn.commit()

    note_updated = None
    if old_file is None:
        print("warning: the old note's front matter was not updated: set vault_path for "
              f"[stores.{r.store}] in {paths.config_path()} or pass the note's full path. "
              "The DB keeps it superseded either way.", file=sys.stderr)
    elif not old_file.exists():
        print(f"warning: {old_file} not found; front matter not updated", file=sys.stderr)
    if old_file and old_file.exists():
        import vault_write
        new_title = Path(new).stem
        vault_write.set_frontmatter(old_file, {"status": "superseded",
                                               "superseded_by": f"[[{new_title}]]"})
        note_updated = str(old_file)

    print(json.dumps({"superseded": old, "by": new, "chunks_marked": len(ids),
                      "note_updated": note_updated}, indent=2))
    return 0


# ---------- Entry point ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=None,
                        help="vector DB (default: the active store's vectors.db)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="create DB schema")
    p_init.set_defaults(func=cmd_init)

    p_arch = sub.add_parser("embed-archive", help="embed a session's archive files")
    p_arch.add_argument("session_id")
    p_arch.add_argument("--project", default=None,
                        help="project (default: resolved from the working directory)")
    p_arch.add_argument("--archive-dir", type=Path, default=None,
                        help="default: <store>/archive/<project>")
    p_arch.add_argument("--processed-dir", type=Path, default=None)
    p_arch.add_argument("--force", action="store_true",
                        help="delete existing chunks for this session before re-embedding")
    p_arch.add_argument("--include-report", action="store_true",
                        help="also embed REPORT_<session-id>.md if present")
    p_arch.set_defaults(func=cmd_embed_archive)

    p_note = sub.add_parser("embed-note", help="embed a single vault note")
    p_note.add_argument("path")
    p_note.add_argument("--project", default=None)
    p_note.set_defaults(func=cmd_embed_note)

    p_stat = sub.add_parser("status", help="show extraction status for a session")
    p_stat.add_argument("session_id")
    p_stat.add_argument("--project", default=None)
    p_stat.add_argument("--processed-dir", type=Path, default=None)
    p_stat.set_defaults(func=cmd_status)

    p_up = sub.add_parser("upgrade", help="bring the DB to the current schema (backs up first)")
    p_up.set_defaults(func=cmd_upgrade)

    p_sup = sub.add_parser("supersede", help="mark a note superseded by another")
    p_sup.add_argument("old", help="the replaced note: path, [[wikilink]], or title")
    p_sup.add_argument("--by", required=True, help="the replacing note: path, [[wikilink]], or title")
    p_sup.add_argument("--folder", default="Decisions", help="vault folder for titles (default Decisions)")
    p_sup.set_defaults(func=cmd_supersede)

    p_re = sub.add_parser("reembed-all", help="detect model mismatches")
    p_re.set_defaults(func=cmd_reembed_all)

    args = parser.parse_args(argv)
    if args.db is None:
        args.db = paths.resolve(project=getattr(args, "project", None)).db
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())