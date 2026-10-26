#!/usr/bin/env python3
"""
recall.py — query the local knowledge base: vector similarity plus keyword
search, merged by reciprocal rank fusion.

Returns ranked chunks with source paths and short snippets. Does not return
full chunk text by default — recall is navigation, not context. If a hit
looks relevant, read the source path directly.

Usage:
  synapse recall "auth strategy for foo"
  synapse recall "retry logic" --project repo-a --type decision
  synapse recall "QuickAddTracker" --mode keyword
  synapse recall "obsidian cli" --since 2026-04-01 --top-k 10 --format text
  synapse recall "mail forwarding" --include-superseded
"""

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Force UTF-8 for stdout/stderr. Windows PowerShell defaults to cp1252,
# which mangles em-dashes and other unicode in retrieved snippets.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Reuse the connection and embedding logic from extract.py — same DB, same
# model, same prefix conventions.
sys.path.insert(0, str(Path(__file__).parent))
import paths  # noqa: E402
from extract import (  # noqa: E402
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    db_connect,
    embed_text,
    require_current,
    vec_project,
)

# Snippet display: short enough to glance, long enough to judge relevance.
SNIPPET_MAX_CHARS = 200
DEFAULT_TOP_K = 5
MAX_KNN_K = 4096  # sqlite-vec refuses a larger k in one KNN query
RRF_K = 60        # reciprocal rank fusion constant: each list adds 1 / (RRF_K + rank)
MODES = ("hybrid", "vector", "keyword")


def candidate_window(top_k: int) -> int:
    """How many candidates each search contributes before fusion."""
    return max(top_k * 4, 20)


def next_window(current: int, got: int, top_k: int, filtered: bool, ceiling: int) -> int | None:
    """The next KNN size to try, or None when the last query was enough.

    Type, project, and status filters run inside the KNN search; only --since
    runs after it, so only a --since query can come back short. Widen
    eightfold until enough rows pass, or the whole DB (or sqlite-vec's
    ceiling) was searched.
    """
    if got >= top_k or not filtered or current >= ceiling:
        return None
    return min(current * 8, ceiling)


def fts_query(text: str) -> str | None:
    """An FTS5 query matching any word of the text. Each word is quoted, so
    punctuation or FTS5 operators in the text cannot change the query."""
    words = re.findall(r"\w+", text)
    return " OR ".join(f'"{w}"' for w in words) or None


def vector_ranked(conn: sqlite3.Connection, embedding: str, top_k: int, project: str | None,
                  source_type: str | None, since: str | None, include_superseded: bool) -> list[int]:
    """Chunk ids nearest the query, filters applied inside the KNN search."""
    filters, params = [], []
    if project:
        filters.append("v.project = ?")
        params.append(vec_project(project))
    if source_type:
        filters.append("v.source_type = ?")
        params.append(source_type)
    if not include_superseded:
        filters.append("v.status = 'active'")
    post = " AND c.created_at >= ?" if since else ""
    sql = (f"SELECT v.rowid AS id FROM chunks_vec v JOIN chunks c ON c.id = v.rowid "
           f"WHERE v.embedding MATCH ? AND k = ?{''.join(' AND ' + f for f in filters)}{post} "
           f"ORDER BY v.distance LIMIT ?")
    want = candidate_window(top_k)
    ceiling = min(MAX_KNN_K, conn.execute("SELECT count(*) FROM chunks").fetchone()[0])
    k = want
    while True:
        rows = conn.execute(sql, [embedding, k, *params, *([since] if since else []), want]).fetchall()
        k = next_window(k, len(rows), want, bool(since), ceiling)
        if k is None:
            return [r["id"] for r in rows]


def keyword_ranked(conn: sqlite3.Connection, text: str, top_k: int, project: str | None,
                   source_type: str | None, since: str | None, include_superseded: bool) -> list[int]:
    """Chunk ids by BM25 over the full-text index, with the same filters."""
    query = fts_query(text)
    if not query:
        return []
    filters, params = [], []
    if project:
        filters.append("py_lower(coalesce(c.project, '')) = ?")
        params.append(vec_project(project))
    if source_type:
        filters.append("c.source_type = ?")
        params.append(source_type)
    if not include_superseded:
        filters.append("c.status = 'active'")
    if since:
        filters.append("c.created_at >= ?")
        params.append(since)
    sql = (f"SELECT chunks_fts.rowid AS id FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
           f"WHERE chunks_fts MATCH ?{''.join(' AND ' + f for f in filters)} "
           f"ORDER BY bm25(chunks_fts) LIMIT ?")
    return [r["id"] for r in conn.execute(sql, [query, *params, candidate_window(top_k)])]


def fuse(vector: list[int], keyword: list[int]) -> list[tuple[int, str]]:
    """Reciprocal rank fusion of two ranked id lists -> [(id, match)], best
    first. Ties keep the vector order."""
    score: dict[int, float] = defaultdict(float)
    kinds: dict[int, set] = defaultdict(set)
    for name, ranked in (("vector", vector), ("keyword", keyword)):
        for rank, cid in enumerate(ranked, 1):
            score[cid] += 1 / (RRF_K + rank)
            kinds[cid].add(name)
    order = sorted(score, key=lambda c: -score[c])
    return [(c, "both" if len(kinds[c]) == 2 else next(iter(kinds[c]))) for c in order]


def search(
    conn: sqlite3.Connection,
    query: str,
    top_k: int,
    project: str | None = None,
    source_type: str | None = None,
    since: str | None = None,
    resolved: "paths.Resolved | None" = None,
    mode: str = "hybrid",
    include_superseded: bool = False,
) -> list[dict]:
    """Run a hybrid (or vector-only, or keyword-only) search with optional
    filters. Returns ranked results."""
    if mode not in MODES:
        sys.exit(f"error: --mode must be one of {', '.join(MODES)}")

    # Verify stored vectors match our current model. If they don't, results
    # will be silently bad — fail loud instead.
    row = conn.execute(
        "SELECT DISTINCT embedding_model FROM chunks LIMIT 2"
    ).fetchall()
    if not row:
        return []
    stored_models = {r["embedding_model"] for r in row}
    if stored_models != {EMBEDDING_MODEL}:
        sys.exit(
            f"error: stored vectors use models {stored_models}, "
            f"but current model is {EMBEDDING_MODEL}. "
            f"run `synapse extract reembed-all` (when implemented) or "
            f"clear the DB and re-ingest."
        )

    embedding = json.dumps(embed_text(query, input_type="query"))
    args = (top_k, project, source_type, since, include_superseded)
    vector = vector_ranked(conn, embedding, *args) if mode != "keyword" else []
    keyword = keyword_ranked(conn, query, *args) if mode != "vector" else []

    results = []
    for cid, match in fuse(vector, keyword)[:top_k]:
        r = conn.execute(
            "SELECT c.*, vec_distance_cosine(v.embedding, ?) AS distance "
            "FROM chunks c JOIN chunks_vec v ON v.rowid = c.id WHERE c.id = ?",
            [embedding, cid],
        ).fetchone()
        metadata = json.loads(r["metadata"]) if r["metadata"] else {}
        text = r["text"]

        # Strip the breadcrumb header we prepended at chunk time — it's
        # already exposed as a structured field.
        body = text
        if text.startswith("[") and "]\n" in text:
            body = text.split("]\n", 1)[1]
        snippet = body.strip().replace("\n", " ")
        if len(snippet) > SNIPPET_MAX_CHARS:
            snippet = snippet[:SNIPPET_MAX_CHARS].rstrip() + "…"

        results.append({
            "score": round(1.0 - r["distance"], 2),  # cosine similarity
            "match": match,
            "source_path": (paths.to_display_path(r["source_path"], resolved)
                            if resolved else r["source_path"]),
            "stored_path": r["source_path"],
            "source_type": r["source_type"],
            "session_id": r["session_id"],
            "project": r["project"],
            "status": r["status"],
            "superseded_by": r["superseded_by"],
            "breadcrumb": metadata.get("breadcrumb", ""),
            "snippet": snippet,
            "created_at": r["created_at"],
        })

    return results


def format_text(results: list[dict], query: str) -> str:
    """Human-readable output for terminal use."""
    if not results:
        return f"no results for: {query}"

    lines = [f"query: {query}", f"{len(results)} result(s):", ""]
    for i, r in enumerate(results, 1):
        lines.append(f"  {i}. [{r['score']}] {r['breadcrumb']}  ({r['match']})")
        lines.append(f"     {r['source_path']}")
        if r["project"]:
            lines.append(f"     project: {r['project']}  type: {r['source_type']}")
        if r["status"] == "superseded":
            lines.append(f"     SUPERSEDED by {r['superseded_by']}")
        lines.append(f"     {r['snippet']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("query", help="natural-language search query")
    parser.add_argument("--db", type=Path, default=None,
                        help="vector DB (default: the active store's vectors.db)")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--project", default=None,
                        help="filter by project (frontmatter project field; case-insensitive)")
    parser.add_argument("--type", dest="source_type", default=None,
                        choices=["decision", "pattern", "archive"],
                        help="filter by source type")
    parser.add_argument("--since", default=None,
                        help="filter by created_at >= this ISO date (YYYY-MM-DD)")
    parser.add_argument("--mode", choices=MODES, default="hybrid",
                        help="hybrid (default), vector, or keyword")
    parser.add_argument("--include-superseded", action="store_true",
                        help="also return chunks of superseded notes, labeled")
    parser.add_argument("--format", choices=["json", "text"], default="json",
                        help="output format (default: json)")
    args = parser.parse_args(argv)

    if args.since:
        # Validate; let bad input fail here rather than silently in SQL.
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            sys.exit(f"error: --since must be ISO format (YYYY-MM-DD), got {args.since!r}")

    resolved = paths.resolve()
    db = args.db or resolved.db
    if not db.exists():
        sys.exit(f"error: DB not found at {db}. run `synapse setup` first.")

    conn = db_connect(db)
    require_current(conn, db)
    results = search(
        conn,
        query=args.query,
        top_k=args.top_k,
        project=args.project,
        source_type=args.source_type,
        since=args.since,
        resolved=resolved,
        mode=args.mode,
        include_superseded=args.include_superseded,
    )

    if args.format == "json":
        print(json.dumps({"query": args.query, "results": results}, indent=2))
    else:
        print(format_text(results, args.query))

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
