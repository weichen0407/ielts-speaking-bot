"""Tests for WikiSearch."""

from pathlib import Path

import pytest

from subagent.cross_session.wiki.processor.schema import WikiPatch, WikiSource
from subagent.cross_session.wiki.processor.wiki_index import WikiIndex
from subagent.cross_session.wiki.processor.wiki_search import WikiSearch


class TestWikiSearch:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    @pytest.fixture
    def searcher(self, wiki_root: Path) -> WikiSearch:
        return WikiSearch(wiki_root=wiki_root)

    @pytest.fixture
    def indexer(self, wiki_root: Path) -> WikiIndex:
        return WikiIndex(wiki_root=wiki_root)

    def test_missing_sqlite_returns_empty(self, searcher: WikiSearch):
        results = searcher.search("basketball")
        assert results == []

    def test_empty_query_returns_empty(self, searcher: WikiSearch):
        results = searcher.search("")
        assert results == []

    def test_missing_fts_returns_empty(self, wiki_root: Path, searcher: WikiSearch, indexer: WikiIndex):
        # Create store but don't build index
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/page",
                title="Test",
                type="ielts_topic",
                mode="ielts",
                section="User Material",
                content="User likes basketball.",
                tags=["sports"],
                topics=["sports"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:1")],
                confidence="medium",
            )
        )
        # searcher doesn't rebuild, so it should return []
        results = searcher.search("basketball")
        assert results == []

    def test_search_finds_results(self, wiki_root: Path, searcher: WikiSearch, indexer: WikiIndex):
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
                content="User enjoys basketball and volleyball.",
                tags=["sports", "hobbies"],
                topics=["sports"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )
        # Manually rebuild
        indexer.rebuild()

        results = searcher.search("basketball")
        assert len(results) >= 1
        assert any(r.slug == "test/sports" for r in results)

    def test_search_mode_filter(self, wiki_root: Path, searcher: WikiSearch, indexer: WikiIndex):
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
                topics=["speaking"],
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
                content="About IELTS speaking.",
                tags=[],
                topics=["speaking"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/freechat",
                title="Freechat Page",
                type="freechat_interest",
                mode="freechat",
                tags=[],
                topics=[],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:3")],
                confidence="medium",
            )
        )
        store.apply_patch(
            WikiPatch(
                operation="merge_section",
                slug="test/freechat",
                title="Freechat Page",
                type="freechat_interest",
                mode="freechat",
                section="Description",
                content="About freechat topics.",
                tags=[],
                topics=[],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:4")],
                confidence="medium",
            )
        )
        indexer.rebuild()

        ielts_results = searcher.search("IELTS speaking", mode="ielts")
        assert all(r.mode == "ielts" for r in ielts_results)

        freechat_results = searcher.search("freechat", mode="freechat")
        assert all(r.mode == "freechat" for r in freechat_results)

    def test_search_topic_filter(self, wiki_root: Path, searcher: WikiSearch, indexer: WikiIndex):
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
                content="About sports topics.",
                tags=["sports"],
                topics=["sports"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )
        indexer.rebuild()

        results = searcher.search("topics", topic="sports")
        assert all("sports" in r.topics for r in results)

    def test_search_tags_filter(self, wiki_root: Path, searcher: WikiSearch, indexer: WikiIndex):
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
                tags=["sports", "hobbies"],
                topics=["sports"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/work",
                title="Work",
                type="ielts_topic",
                mode="ielts",
                tags=["work"],
                topics=["work"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:3")],
                confidence="medium",
            )
        )
        store.apply_patch(
            WikiPatch(
                operation="merge_section",
                slug="test/work",
                title="Work",
                type="ielts_topic",
                mode="ielts",
                section="User Material",
                content="User talks about basketball at work.",
                tags=["work"],
                topics=["work"],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:4")],
                confidence="medium",
            )
        )
        indexer.rebuild()

        results = searcher.search("basketball", tags=["hobbies"])
        assert results
        assert all("hobbies" in r.tags for r in results)

    def test_search_limit(self, wiki_root: Path, searcher: WikiSearch, indexer: WikiIndex):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        for i in range(5):
            store.apply_patch(
                WikiPatch(
                    operation="create_page",
                    slug=f"test/page{i}",
                    title=f"Page {i}",
                    type="ielts_topic",
                    mode="ielts",
                    tags=["hobbies"],
                    topics=["sports"],
                    links=[],
                    sources=[WikiSource(kind="session", session_id="x", message_id=f"u:{i}")],
                    confidence="medium",
                )
            )
            store.apply_patch(
                WikiPatch(
                    operation="merge_section",
                    slug=f"test/page{i}",
                    title=f"Page {i}",
                    type="ielts_topic",
                    mode="ielts",
                    section="User Material",
                    content=f"Content about basketball {i}.",
                    tags=["hobbies"],
                    topics=["sports"],
                    links=[],
                    sources=[WikiSource(kind="session", session_id="x", message_id=f"u:{i+10}")],
                    confidence="medium",
                )
            )
        indexer.rebuild()

        results = searcher.search("basketball", limit=3)
        assert len(results) == 3
