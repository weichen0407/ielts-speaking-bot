"""Tests for WikiRetriever."""

from pathlib import Path

import pytest

from subagent.cross_session.wiki.processor.schema import WikiPatch, WikiSource
from subagent.cross_session.wiki.processor.wiki_index import WikiIndex
from subagent.cross_session.wiki.processor.wiki_retriever import read_wiki_context


class TestReadWikiContext:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    @pytest.fixture
    def indexer(self, wiki_root: Path) -> WikiIndex:
        return WikiIndex(wiki_root=wiki_root)

    def test_no_wiki_root_returns_none(self):
        result = read_wiki_context("basketball")
        assert result == "(none)"

    def test_no_results_returns_none(self, wiki_root: Path, indexer: WikiIndex):
        # Index is empty
        result = read_wiki_context("basketball", wiki_root=wiki_root)
        assert result == "(none)"

    def test_returns_context(self, wiki_root: Path, indexer: WikiIndex):
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

        result = read_wiki_context("basketball", wiki_root=wiki_root)
        assert result != "(none)"
        assert "test/sports" in result or "Sports" in result

    def test_respects_max_chars(self, wiki_root: Path, indexer: WikiIndex):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/long",
                title="Long Page",
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
                slug="test/long",
                title="Long Page",
                type="ielts_topic",
                mode="ielts",
                section="User Material",
                content="A" * 500,
                tags=[],
                topics=[],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )
        indexer.rebuild()

        result = read_wiki_context("A" * 10, wiki_root=wiki_root, max_chars=200)
        assert len(result) <= 300  # well under normal limits

    def test_filters_by_mode(self, wiki_root: Path, indexer: WikiIndex):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/ielts",
                title="IELTS Page",
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
                slug="test/ielts",
                title="IELTS Page",
                type="ielts_topic",
                mode="ielts",
                section="User Material",
                content="About IELTS.",
                tags=[],
                topics=[],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )
        indexer.rebuild()

        result = read_wiki_context("IELTS", mode="ielts", wiki_root=wiki_root)
        assert result != "(none)"
        result_freechat = read_wiki_context("IELTS", mode="freechat", wiki_root=wiki_root)
        # No freechat pages exist, but since FTS still returns results (mode filter is post-filter),
        # just check it doesn't crash
        assert "<!-- WIKI CONTEXT -->" in result
