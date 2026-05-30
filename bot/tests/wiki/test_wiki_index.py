"""Tests for WikiIndex."""

import json
from pathlib import Path

import pytest

from subagent.cross_session.wiki.processor.schema import WikiPatch, WikiSource
from subagent.cross_session.wiki.processor.wiki_index import WikiIndex, _iter_chunks


class TestIterChunks:
    @pytest.mark.parametrize(
        "body, expected",
        [
            (
                "## Summary\n\nSummary text.\n\n## User Material\n\nUser likes basketball.",
                [("Summary", "Summary text."), ("User Material", "User likes basketball.")],
            ),
            (
                "Intro text.\n\n## Section One\n\nContent.",
                [("", "Intro text."), ("Section One", "Content.")],
            ),
            (
                "## Only\n\nContent only.",
                [("Only", "Content only.")],
            ),
        ],
    )
    def test_splits_by_sections(self, body: str, expected: list[tuple[str, str]]):
        result = list(_iter_chunks(body))
        assert result == expected

    def test_skips_empty_sections(self):
        body = "## Summary\n\n\n\n## Empty\n\n   \n\n## Content\n\nReal."
        result = list(_iter_chunks(body))
        assert result == [("Content", "Real.")]


class TestWikiIndex:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    @pytest.fixture
    def index(self, wiki_root: Path) -> WikiIndex:
        return WikiIndex(wiki_root=wiki_root)

    def test_init_creates_tables(self, index: WikiIndex):
        index.init()
        conn = index._conn()
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [r["name"] for r in cur.fetchall()]
            assert "pages" in tables
            assert "chunks" in tables
            assert "chunks_fts" in tables
        finally:
            conn.close()

    def test_rebuild_empty(self, index: WikiIndex):
        count = index.rebuild()
        assert count == 0

    def test_rebuild_indexes_pages(self, wiki_root: Path, index: WikiIndex):
        # Create a page via WikiStore
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/sports",
                title="Sports",
                type="ielts_topic",
                mode="ielts",
                tags=["sports"],
                topics=["sports"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:1")],
                confidence="medium",
            )
        )
        store.apply_patch(
            WikiPatch(
                operation="merge_section",
                slug="test/sports",
                title="Sports",
                type="ielts_topic",
                mode="ielts",
                section="User Material",
                content="User enjoys basketball.",
                tags=["sports"],
                topics=["sports"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )

        store.apply_patch(
            WikiPatch(
                operation="merge_section",
                slug="test/sports",
                title="Sports",
                type="ielts_topic",
                mode="ielts",
                section="User Material",
                content="User plays volleyball too.",
                tags=["sports"],
                topics=["sports"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:3")],
                confidence="medium",
            )
        )

        count = index.rebuild()
        assert count >= 1  # at least 1 chunk from User Material

        # Verify pages table
        conn = index._conn()
        try:
            cur = conn.execute("SELECT slug, title, type, mode FROM pages")
            rows = {r["slug"]: r for r in cur.fetchall()}
            assert "test/sports" in rows
            assert rows["test/sports"]["title"] == "Sports"
        finally:
            conn.close()

    def test_index_page_adds_chunks(self, wiki_root: Path, index: WikiIndex):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/page",
                title="Test Page",
                type="ielts_topic",
                mode="ielts",
                tags=[],
                topics=[],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:1")],
                confidence="medium",
            )
        )
        store.apply_patch(
            WikiPatch(
                operation="merge_section",
                slug="test/page",
                title="Test Page",
                type="ielts_topic",
                mode="ielts",
                section="User Material",
                content="Some content.",
                tags=[],
                topics=[],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )

        index.init()
        count = index.index_page("test/page")
        assert count >= 1

        conn = index._conn()
        try:
            cur = conn.execute(
                "SELECT section, content FROM chunks WHERE slug = 'test/page'"
            )
            chunks = list(cur.fetchall())
            assert len(chunks) >= 1
        finally:
            conn.close()

    def test_delete_page(self, wiki_root: Path, index: WikiIndex):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/delete-me",
                title="Delete Me",
                type="ielts_topic",
                mode="ielts",
                section="User Material",
                content="To be deleted.",
                tags=[],
                topics=[],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:1")],
                confidence="medium",
            )
        )
        index.rebuild()

        index.delete_page("test/delete-me")

        conn = index._conn()
        try:
            cur = conn.execute("SELECT slug FROM pages WHERE slug = 'test/delete-me'")
            assert cur.fetchone() is None
        finally:
            conn.close()
