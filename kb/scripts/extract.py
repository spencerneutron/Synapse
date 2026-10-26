#!/usr/bin/env python3
"""
extract.py — chunk, embed, and store session archive content and vault notes.

Subcommands:
  init                       Create DB schema if missing.
  embed-archive <session-id> Embed PLAN/EXECUTION/NOTES files for one session.
  embed-note <path>          Embed a single vault note (decision/pattern/session).
  status <session-id>        Report extraction status for a session.
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
# usually does not carry sqlite-vec. The project keeps sqlite-vec in a local venv at
# kb/.venv. If the current interpreter can't import sqlite_vec, re-exec under
# the venv interpreter so callers (and the /recall + /extract-session skills)
# don't have to know which python to use. recall.py imports this module and
# backfill.py shells out to it, so both inherit the fix automatically.
def _reexec_under_venv_if_needed() -> None:
    import importlib.util

    if importlib.util.find_spec("sqlite_vec") is not None:
        return  # current interpreter already has it — nothing to do
    if os.environ.get("KB_VENV_REEXEC") == "1":
        return  # already re-exec'd once; fall through to the clear error path

    here = Path(__file__).resolve()
    if sys.platform == "win32":
        venv_python = here.parent.parent / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = here.parent.parent / ".venv" / "bin" / "python"

    # No venv to fall back to: let the normal "sqlite-vec not installed" error
    # in db_connect() speak for itself. We deliberately do NOT compare
    # sys.executable to the venv python — a venv interpreter is a symlink to the
    # same base binary, so the two resolve() identically and the comparison
    # always misfires. The find_spec check above already proves this interpreter
    # lacks sqlite-vec, and the KB_VENV_REEXEC sentinel stops an infinite loop
    # if the venv somehow lacks it too.
    if not venv_python.exists():
        return

    os.environ["KB_VENV_REEXEC"] = "1"
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

# Chunking targets. Tokens are approximated as words * 1.3 — close enough
# for boundary decisions; the embedding model has its own tokenizer.
CHUNK_TARGET_WORDS = 500       # ~650 tokens
CHUNK_MAX_WORDS = 800          # ~1000 tokens, hard ceiling
CHUNK_MIN_WORDS = 30           # below this, merge with neighbor

DEFAULT_DB_PATH = Path(".claude-work/kb/vectors.db")
DEFAULT_ARCHIVE_DIR = Path(".claude-work/archive")
DEFAULT_PROCESSED_DIR = Path(".claude-work/archive/.processed")


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
        sys.exit("error: sqlite-vec not installed. run: pip install sqlite-vec")

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
    return conn


def db_init(conn: sqlite3.Connection) -> None:
    """Create schema. Safe to call repeatedly."""
    conn.executescript(f"""
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
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_session ON chunks(session_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_project ON chunks(project);
        CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(source_type);

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
            embedding FLOAT[{EMBEDDING_DIM}] distance_metric=cosine
        );
    """)
    conn.commit()


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
        with urllib.request.urlopen(req, timeout=30) as resp:
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

def store_chunks(conn: sqlite3.Connection, chunks: list[Chunk]) -> tuple[int, int]:
    """Embed and insert chunks. Returns (inserted, skipped) counts."""
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

        cursor = conn.execute(
            """
            INSERT INTO chunks (
                chunk_hash, source_path, source_type, session_id, project,
                chunk_index, text, metadata, embedding_model, embedding_dim,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_hash, chunk.source_path, chunk.source_type,
                chunk.session_id, chunk.project, chunk.chunk_index,
                chunk.text, json.dumps(chunk.metadata),
                EMBEDDING_MODEL, EMBEDDING_DIM, now,
            ),
        )
        chunk_id = cursor.lastrowid
        # sqlite-vec wants the embedding as a JSON array string.
        conn.execute(
            "INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
            (chunk_id, json.dumps(emb)),
        )
        inserted += 1

    conn.commit()
    return inserted, skipped


# ---------- Subcommands ----------

def cmd_init(args: argparse.Namespace) -> int:
    conn = db_connect(args.db)
    db_init(conn)
    print(f"initialized {args.db}")
    return 0


def cmd_embed_archive(args: argparse.Namespace) -> int:
    archive_dir = Path(args.archive_dir)
    session_id = args.session_id
    project = args.project

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
    db_init(conn)

    if args.force:
        # Delete existing chunks for this session so re-ingest produces
        # fresh vectors. Use a transaction so chunks and vectors stay in sync.
        deleted = conn.execute(
            "SELECT id FROM chunks WHERE session_id = ?", (session_id,)
        ).fetchall()
        if deleted:
            ids = [row["id"] for row in deleted]
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM chunks_vec WHERE rowid IN ({placeholders})", ids)
            conn.execute("DELETE FROM chunks WHERE session_id = ?", (session_id,))
            conn.commit()
            print(f"  --force: cleared {len(ids)} existing chunks for session {session_id}")

    total_inserted = 0
    total_skipped = 0

    for path in files_to_embed:
        content = path.read_text(encoding="utf-8")
        chunks = chunk_document(
            content=content,
            source_path=str(path),
            source_type="archive",
            session_id=session_id,
            project=project,
        )
        inserted, skipped = store_chunks(conn, chunks)
        total_inserted += inserted
        total_skipped += skipped
        print(f"  {path.name}: {inserted} new, {skipped} unchanged")

    # Write processed marker.
    processed_dir = Path(args.processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    marker = processed_dir / f"{session_id}.json"
    marker.write_text(json.dumps({
        "session_id": session_id,
        "project": project,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": EMBEDDING_MODEL,
        "files": [str(p) for p in files_to_embed],
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
    project = frontmatter.get("project") or args.project

    conn = db_connect(args.db)
    db_init(conn)

    # Always-replace semantics: vault notes can be edited (manually or by
    # re-extraction). Delete any existing chunks for this exact source_path
    # before re-inserting. Without this, edited content produces duplicate
    # chunks (old + new versions both present in the DB), which corrupts
    # recall results. There's no `--force` flag for this command — replacement
    # is the only correct behavior for note re-embedding.
    source_path_str = str(path)
    existing = conn.execute(
        "SELECT id FROM chunks WHERE source_path = ?", (source_path_str,)
    ).fetchall()
    if existing:
        ids = [row["id"] for row in existing]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM chunks_vec WHERE rowid IN ({placeholders})", ids)
        conn.execute("DELETE FROM chunks WHERE source_path = ?", (source_path_str,))
        conn.commit()
        print(f"  cleared {len(ids)} existing chunks for {path.name}")

    chunks = chunk_document(
        content=content,
        source_path=source_path_str,
        source_type=source_type,
        session_id=session_id,
        project=project,
    )
    inserted, skipped = store_chunks(conn, chunks)
    print(f"{path.name}: {inserted} new, {skipped} unchanged")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    marker = Path(args.processed_dir) / f"{args.session_id}.json"
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


# ---------- Entry point ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="create DB schema")
    p_init.set_defaults(func=cmd_init)

    p_arch = sub.add_parser("embed-archive", help="embed a session's archive files")
    p_arch.add_argument("session_id")
    p_arch.add_argument("--project", default=None)
    p_arch.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    p_arch.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
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
    p_stat.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    p_stat.set_defaults(func=cmd_status)

    p_re = sub.add_parser("reembed-all", help="detect model mismatches")
    p_re.set_defaults(func=cmd_reembed_all)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())