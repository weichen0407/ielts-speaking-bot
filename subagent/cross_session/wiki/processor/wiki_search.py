"""WikiSearch - SQLite FTS search for the LLM Wiki Memory System.

WikiSearch must NOT rebuild the index in __init__.
If SQLite or FTS is missing, search returns [].
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .schema import WikiSearchResult


# ---------------------------------------------------------------------------
# WikiSearch
# ---------------------------------------------------------------------------


class WikiSearch:
    """FTS5-powered search over wiki pages."""

    def __init__(self, wiki_root: Path):
        self.wiki_root = Path(wiki_root)
        self.db_path = self.wiki_root / "index" / "wiki.sqlite"

    def _conn(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            return None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            return None

    def _fts_available(self, conn: sqlite3.Connection) -> bool:
        """Check if FTS5 virtual table exists."""
        try:
            cur = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
            )
            return cur.fetchone() is not None
        except sqlite3.Error:
            return False

    def search(
        self,
        query: str,
        *,
        mode: str | None = None,
        topic: str | None = None,
        page_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[WikiSearchResult]:
        """Search wiki chunks by text query with optional filters.

        Returns empty list if SQLite or FTS is unavailable.
        """
        if not query.strip():
            return []

        conn = self._conn()
        if conn is None:
            return []
        try:
            if not self._fts_available(conn):
                return []

            # Build filter conditions
            conditions: list[str] = []
            params: list = []

            if mode:
                conditions.append("p.mode = ?")
                params.append(mode)

            if topic:
                conditions.append("p.topics LIKE ?")
                params.append(f'%"{topic}"%')

            if page_type:
                conditions.append("p.type = ?")
                params.append(page_type)

            if tags:
                for tag in tags:
                    conditions.append("p.tags LIKE ?")
                    params.append(f'%"{tag}"%')

            where_clause = " AND ".join(conditions) if conditions else "1=1"

            # FTS5 search with BM25 ranking
            sql = f"""
                SELECT
                    p.slug,
                    p.title,
                    p.type,
                    p.mode,
                    c.section,
                    snippet(chunks_fts, 0, '==', '==', '...', 32) AS snippet,
                    bm25(chunks_fts) AS score,
                    p.tags,
                    p.topics
                FROM chunks_fts f
                JOIN chunks c ON c.id = f.rowid
                JOIN pages p ON p.slug = c.slug
                WHERE chunks_fts MATCH ?
                  AND {where_clause}
                ORDER BY score
                LIMIT ?
            """
            params = [query, *params, limit]

            cur = conn.execute(sql, params)
            rows = cur.fetchall()

            results: list[WikiSearchResult] = []
            seen_slugs: set[str] = set()

            for row in rows:
                slug = row["slug"]
                # Deduplicate by slug (keep best-scoring chunk per page)
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                results.append(
                    WikiSearchResult(
                        slug=row["slug"],
                        title=row["title"],
                        type=row["type"],
                        mode=row["mode"],
                        section=row["section"],
                        snippet=row["snippet"] or "",
                        score=abs(row["score"] or 0.0),
                        tags=json.loads(row["tags"] or "[]"),
                        topics=json.loads(row["topics"] or "[]"),
                    )
                )

            return results
        except sqlite3.Error:
            return []
        finally:
            conn.close()
