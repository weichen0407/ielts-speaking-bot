"""Tests for Wiki API handlers via WebSocket channel.

These tests verify the wiki HTTP API routes work correctly by testing the
underlying components (WikiStore, WikiSearch, WikiIndex, WikiGraph) and
verifying the route handler logic.
"""

from pathlib import Path
import json

import pytest

from subagent.cross_session.wiki.processor.schema import WikiPatch, WikiSource
from subagent.cross_session.wiki.processor.wiki_index import WikiIndex
from subagent.cross_session.wiki.processor.wiki_search import WikiSearch
from subagent.cross_session.wiki.processor.wiki_graph import build_wiki_graph


class TestWikiAPISearch:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    @pytest.fixture
    def indexer(self, wiki_root: Path) -> WikiIndex:
        return WikiIndex(wiki_root=wiki_root)

    def test_search_returns_results_list(self, wiki_root: Path, indexer: WikiIndex):
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
        indexer.rebuild()

        searcher = WikiSearch(wiki_root=wiki_root)
        results = searcher.search("basketball")
        assert isinstance(results, list)
        assert len(results) >= 1
        assert results[0].slug == "test/sports"
        assert results[0].title == "Sports"


class TestWikiAPIPage:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    def test_page_returns_meta_and_content(self, wiki_root: Path):
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

        page = store.read_page("test/sports")
        assert page is not None
        meta, body = page
        assert meta.slug == "test/sports"
        assert meta.title == "Sports"
        assert isinstance(body, str)
        assert "## Summary" in body

    def test_missing_page_returns_none(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        page = store.read_page("nonexistent/page")
        assert page is None


class TestWikiAPIPatch:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    def test_apply_valid_patch(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        patch = WikiPatch(
            operation="create_page",
            slug="test/new",
            title="New Page",
            type="ielts_topic",
            mode="ielts",
            tags=["test"],
            topics=["test"],
            links=[],
            sources=[WikiSource(kind="session", session_id="x", message_id="u:1")],
            confidence="medium",
        )
        ok = store.apply_patch(patch)
        assert ok is True

        page = store.read_page("test/new")
        assert page is not None

    def test_rejected_patch_returns_false(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        # replace_section without reason is rejected at apply time
        patch = WikiPatch(
            operation="replace_section",
            slug="test/bad",
            title="Bad",
            type="ielts_topic",
            mode="ielts",
            section="Summary",
            content="New content.",
            tags=[],
            topics=[],
            links=[],
            sources=[WikiSource(kind="session", session_id="x", message_id="u:1")],
            confidence="medium",
            reason=None,
        )
        ok = store.apply_patch(patch)
        assert ok is False


class TestWikiAPIIndex:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    def test_rebuild_index(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/page",
                title="Test",
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
                title="Test",
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

        indexer = WikiIndex(wiki_root=wiki_root)
        count = indexer.rebuild()
        assert count >= 1

        # Verify page is in index
        conn = indexer._conn()
        try:
            cur = conn.execute("SELECT slug FROM pages")
            slugs = [r["slug"] for r in cur.fetchall()]
            assert "test/page" in slugs
        finally:
            conn.close()


class TestWikiAPIGraph:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    def test_graph_returns_nodes_and_edges(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/sports",
                title="Sports",
                type="ielts_topic",
                mode="ielts",
                tags=["sports", "hobbies"],
                topics=["sports"],
                links=["user/preferences"],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:1")],
                confidence="medium",
            )
        )

        graph = build_wiki_graph(wiki_root)
        assert "nodes" in graph
        assert "edges" in graph
        assert isinstance(graph["nodes"], list)
        assert isinstance(graph["edges"], list)

    def test_empty_wiki_does_not_crash(self, wiki_root: Path):
        graph = build_wiki_graph(wiki_root)
        assert graph["nodes"] == []
        assert graph["edges"] == []
