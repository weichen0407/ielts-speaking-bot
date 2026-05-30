"""WikiIndex - SQLite FTS index for the LLM Wiki Memory System.

Tables:
  - pages: slug, title, type, mode, tags (JSON), topics (JSON), updated_at
  - chunks: id, slug, section, content, chunk_index
  - chunks_fts: FTS5 virtual table over chunks(content)

Index is derived from Markdown pages. Rebuild is explicit via rebuild().
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Iterator

from .schema import WikiPageMeta, WikiSearchResult


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    slug      TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    type      TEXT NOT NULL,
    mode      TEXT NOT NULL,
    tags      TEXT NOT NULL DEFAULT '[]',
    topics    TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL,
    section     TEXT NOT NULL,
    content     TEXT NOT NULL,
    chunk_index INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (slug) REFERENCES pages(slug) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='id'
);
"""


def _iter_chunks(body: str) -> Iterator[tuple[str, str]]:
    """Split a page body into (section_name, chunk_content) chunks.

    Sections are split by ## headings. Each section is one chunk.
    Very long sections (>2000 chars) are further split by blank-line paragraphs.
    """
    sections: dict[str, list[str]] = {}
    current_name = ""
    current_lines: list[str] = []

    for line in body.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+)\s*$", line)
        if m:
            if current_lines:
                sections[current_name] = current_lines
                current_lines = []
            current_name = m.group(2).strip()
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_name] = current_lines

    for section_name, lines in sections.items():
        content = "\n".join(lines).strip()
        if not content:
            continue

        # Split very long sections by blank lines (paragraphs)
        if len(content) > 2000:
            paragraphs: list[str] = []
            para_lines: list[str] = []
            for l in lines:
                if l.strip() == "":
                    if para_lines:
                        paragraphs.append("\n".join(para_lines).strip())
                        para_lines = []
                else:
                    para_lines.append(l)
            if para_lines:
                paragraphs.append("\n".join(para_lines).strip())

            for idx, para in enumerate(paragraphs):
                if para:
                    yield section_name, para
        else:
            yield section_name, content


# ---------------------------------------------------------------------------
# WikiIndex
# ---------------------------------------------------------------------------


class WikiIndex:
    """SQLite FTS index for wiki pages."""

    def __init__(self, wiki_root: Path):
        self.wiki_root = Path(wiki_root)
        self.index_root = self.wiki_root / "index"
        self.db_path = self.index_root / "wiki.sqlite"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.index_root.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        """Create tables if they don't exist."""
        conn = self._conn()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def rebuild(self) -> int:
        """Rebuild the entire index from Markdown pages.

        Returns the number of chunks indexed.
        """
        # Import here to avoid circular dependency
        from .wiki_store import WikiStore

        self.init()

        conn = self._conn()
        try:
            # Clear existing data
            conn.execute("DELETE FROM chunks_fts WHERE rowid NOT NULL")
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM pages")
            conn.commit()

            # Index all pages
            store = WikiStore(workspace=self.wiki_root.parent, wiki_root=self.wiki_root)
            total_chunks = 0

            for page_meta in store.list_pages():
                slug = page_meta.slug
                page = store.read_page(slug)
                if not page:
                    continue

                meta, body = page

                # Upsert page
                conn.execute(
                    """
                    INSERT OR REPLACE INTO pages (slug, title, type, mode, tags, topics, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        meta.slug,
                        meta.title,
                        meta.type,
                        meta.mode,
                        json.dumps(meta.tags),
                        json.dumps(meta.topics),
                        meta.updated_at,
                    ),
                )

                # Delete old chunks for this slug
                conn.execute("DELETE FROM chunks WHERE slug = ?", (slug,))

                # Insert new chunks
                chunk_index = 0
                for section_name, chunk_content in _iter_chunks(body):
                    conn.execute(
                        """
                        INSERT INTO chunks (slug, section, content, chunk_index)
                        VALUES (?, ?, ?, ?)
                        """,
                        (slug, section_name, chunk_content, chunk_index),
                    )
                    chunk_index += 1
                    total_chunks += 1

            # Rebuild FTS
            conn.execute(
                """
                INSERT INTO chunks_fts(rowid, content)
                SELECT id, content FROM chunks
                """
            )
            conn.commit()
            return total_chunks
        finally:
            conn.close()

    def index_page(self, slug: str) -> int:
        """Index or re-index a single page.

        Returns the number of chunks indexed.
        """
        # Import here to avoid circular dependency
        from .wiki_store import WikiStore

        self.init()

        conn = self._conn()
        try:
            store = WikiStore(workspace=self.wiki_root.parent, wiki_root=self.wiki_root)
            page = store.read_page(slug)
            if not page:
                return 0

            meta, body = page

            # Upsert page
            conn.execute(
                """
                INSERT OR REPLACE INTO pages (slug, title, type, mode, tags, topics, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meta.slug,
                    meta.title,
                    meta.type,
                    meta.mode,
                    json.dumps(meta.tags),
                    json.dumps(meta.topics),
                    meta.updated_at,
                ),
            )

            # Remove old chunks
            conn.execute("DELETE FROM chunks WHERE slug = ?", (slug,))
            conn.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE slug = ?)", (slug,))

            # Insert new chunks
            chunk_index = 0
            for section_name, chunk_content in _iter_chunks(body):
                conn.execute(
                    """
                    INSERT INTO chunks (slug, section, content, chunk_index)
                    VALUES (?, ?, ?, ?)
                    """,
                    (slug, section_name, chunk_content, chunk_index),
                )
                chunk_index += 1

            # Rebuild FTS for this page's chunks
            conn.execute(
                """
                INSERT INTO chunks_fts(rowid, content)
                SELECT id, content FROM chunks WHERE slug = ?
                """,
                (slug,),
            )
            conn.commit()
            return chunk_index
        finally:
            conn.close()

    def delete_page(self, slug: str) -> None:
        """Remove a page from the index."""
        self.init()
        conn = self._conn()
        try:
            conn.execute("DELETE FROM chunks WHERE slug = ?", (slug,))
            conn.execute("DELETE FROM pages WHERE slug = ?", (slug,))
            conn.commit()
        finally:
            conn.close()
