#!/usr/bin/env python3
"""
recall.py — query the local knowledge base by semantic similarity.

Returns ranked chunks with source paths and short snippets. Does not return
full chunk text by default — recall is navigation, not context. If a hit
looks relevant, read the source path directly.

Usage:
  recall.py "auth strategy for foo"
  recall.py "retry logic" --project repo-a --type decision
  recall.py "obsidian cli" --since 2026-04-01 --top-k 10 --format text
"""

import argparse
import json
import sqlite3
import sys
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
from extract import (  # noqa: E402
    DEFAULT_DB_PATH,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    db_connect,
    embed_text,
)

# Snippet display: short enough to glance, long enough to judge relevance.
SNIPPET_MAX_CHARS = 200
DEFAULT_TOP_K = 5


def search(
    conn: sqlite3.Connection,
    query: str,
    top_k: int,
    project: str | None = None,
    source_type: str | None = None,
    since: str | None = None,
) -> list[dict]:
    """Run a semantic search with optional filters. Returns ranked results."""

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
            f"run `extract.py reembed-all` (when implemented) or "
            f"clear the DB and re-ingest."
        )

    query_embedding = embed_text(query, input_type="query")

    # sqlite-vec's KNN query. We over-fetch then filter in SQL because
    # vec0 doesn't support arbitrary WHERE clauses on joined tables in
    # the MATCH itself. Fetching 4x top_k is a generous overshoot.
    over_fetch = max(top_k * 4, 20)

    # Build the filter clause dynamically.
    filters = []
    params: list = []
    if project:
        filters.append("c.project = ?")
        params.append(project)
    if source_type:
        filters.append("c.source_type = ?")
        params.append(source_type)
    if since:
        filters.append("c.created_at >= ?")
        params.append(since)
    where_clause = (" AND " + " AND ".join(filters)) if filters else ""

    sql = f"""
        SELECT
            c.id,
            c.source_path,
            c.source_type,
            c.session_id,
            c.project,
            c.text,
            c.metadata,
            c.created_at,
            v.distance
        FROM chunks_vec v
        JOIN chunks c ON c.id = v.rowid
        WHERE v.embedding MATCH ?
          AND k = ?
          {where_clause}
        ORDER BY v.distance
        LIMIT ?
    """

    rows = conn.execute(
        sql,
        [json.dumps(query_embedding), over_fetch, *params, top_k],
    ).fetchall()

    results = []
    for r in rows:
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
            "source_path": r["source_path"],
            "source_type": r["source_type"],
            "session_id": r["session_id"],
            "project": r["project"],
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
        lines.append(f"  {i}. [{r['score']}] {r['breadcrumb']}")
        lines.append(f"     {r['source_path']}")
        if r["project"]:
            lines.append(f"     project: {r['project']}  type: {r['source_type']}")
        lines.append(f"     {r['snippet']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("query", help="natural-language search query")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--project", default=None,
                        help="filter by project (frontmatter project field)")
    parser.add_argument("--type", dest="source_type", default=None,
                        choices=["session", "decision", "pattern", "archive"],
                        help="filter by source type")
    parser.add_argument("--since", default=None,
                        help="filter by created_at >= this ISO date (YYYY-MM-DD)")
    parser.add_argument("--format", choices=["json", "text"], default="json",
                        help="output format (default: json)")
    args = parser.parse_args(argv)

    if args.since:
        # Validate; let bad input fail here rather than silently in SQL.
        try:
            datetime.fromisoformat(args.since)
        except ValueError:
            sys.exit(f"error: --since must be ISO format (YYYY-MM-DD), got {args.since!r}")

    if not args.db.exists():
        sys.exit(f"error: DB not found at {args.db}. run `extract.py init` first.")

    conn = db_connect(args.db)
    results = search(
        conn,
        query=args.query,
        top_k=args.top_k,
        project=args.project,
        source_type=args.source_type,
        since=args.since,
    )

    if args.format == "json":
        print(json.dumps({"query": args.query, "results": results}, indent=2))
    else:
        print(format_text(results, args.query))

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())