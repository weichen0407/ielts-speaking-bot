"""Tests for WikiGraph."""

from pathlib import Path

import pytest

from subagent.cross_session.wiki.processor.schema import WikiPatch, WikiSource
from subagent.cross_session.wiki.processor.wiki_graph import build_wiki_graph, WikiGraphNode, WikiGraphEdge


class TestWikiGraph:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    def test_empty_wiki(self, wiki_root: Path):
        graph = build_wiki_graph(wiki_root)
        assert graph["nodes"] == []
        assert graph["edges"] == []

    def test_page_node(self, wiki_root: Path):
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
        nodes = graph["nodes"]
        page_node = next((n for n in nodes if n["id"] == "test/sports"), None)
        assert page_node is not None
        assert page_node["label"] == "Sports"
        assert page_node["kind"] == "page"
        assert page_node["type"] == "ielts_topic"
        assert page_node["mode"] == "ielts"
        assert "sports" in page_node["tags"]

    def test_tag_nodes(self, wiki_root: Path):
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

        graph = build_wiki_graph(wiki_root)
        tag_node = next((n for n in graph["nodes"] if n["id"] == "tag:sports"), None)
        assert tag_node is not None
        assert tag_node["kind"] == "tag"
        assert tag_node["label"] == "sports"

        edges = graph["edges"]
        tag_edge = next((e for e in edges if e["kind"] == "has_tag" and e["source"] == "test/sports"), None)
        assert tag_edge is not None

    def test_mode_node(self, wiki_root: Path):
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

        graph = build_wiki_graph(wiki_root)
        mode_node = next((n for n in graph["nodes"] if n["id"] == "mode:ielts"), None)
        assert mode_node is not None
        assert mode_node["kind"] == "mode"

    def test_filter_by_mode(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/ielts",
                title="IELTS",
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
                operation="create_page",
                slug="test/freechat",
                title="Freechat",
                type="freechat_interest",
                mode="freechat",
                tags=[],
                topics=[],
                links=[],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:2")],
                confidence="medium",
            )
        )

        graph_ielts = build_wiki_graph(wiki_root, mode="ielts")
        page_nodes = [n for n in graph_ielts["nodes"] if n["kind"] == "page"]
        assert all(n["mode"] == "ielts" for n in page_nodes)

        graph_all = build_wiki_graph(wiki_root)
        page_ids = [n["id"] for n in graph_all["nodes"] if n["kind"] == "page"]
        assert "test/ielts" in page_ids
        assert "test/freechat" in page_ids

    def test_filter_by_topic(self, wiki_root: Path):
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

        graph = build_wiki_graph(wiki_root, topic="sports")
        page_ids = [n["id"] for n in graph["nodes"] if n["kind"] == "page"]
        assert "test/sports" in page_ids

        graph_other = build_wiki_graph(wiki_root, topic="other")
        page_ids_other = [n["id"] for n in graph_other["nodes"] if n["kind"] == "page"]
        assert "test/sports" not in page_ids_other

    def test_link_edges(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="create_page",
                slug="test/sports",
                title="Sports",
                type="ielts_topic",
                mode="ielts",
                tags=[],
                topics=[],
                links=["user/preferences"],
                sources=[WikiSource(kind="session", session_id="x", message_id="u:1")],
                confidence="medium",
            )
        )

        graph = build_wiki_graph(wiki_root)
        link_edge = next((e for e in graph["edges"] if e["kind"] == "link"), None)
        assert link_edge is not None
        assert link_edge["source"] == "test/sports"
        assert link_edge["target"] == "user/preferences"
