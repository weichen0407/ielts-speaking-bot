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
        assert page_node["type"] == "concept"
        assert page_node["mode"] == "ielts"
        assert "sports" in page_node["tags"]

    def test_topic_cluster_nodes(self, wiki_root: Path):
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
        topic_node = next((n for n in graph["nodes"] if n["id"] == "topic:sports"), None)
        assert topic_node is not None
        assert topic_node["kind"] == "topic"
        assert topic_node["label"] == "sports"
        assert topic_node["size"] >= 8

        edges = graph["edges"]
        topic_edge = next((e for e in edges if e["kind"] == "has_topic" and e["source"] == "test/sports"), None)
        assert topic_edge is not None

    def test_schema_nodes_are_hidden(self, wiki_root: Path):
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
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "mode:ielts" not in node_ids
        assert "type:concept" not in node_ids
        assert not any(node_id.startswith("tag:") for node_id in node_ids)
        fallback_topic = next((n for n in graph["nodes"] if n["id"] == "topic:ielts/general"), None)
        assert fallback_topic is not None

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

    def test_entity_and_concept_nodes_from_frontmatter(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.schema import WikiPageMeta
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.write_page(
            WikiPageMeta(
                slug="user/profile",
                title="User Profile",
                type="entity",
                mode="global",
                topics=["personal"],
                entities=["user"],
                concepts=["learning-style"],
                sources=["manual:test"],
                created_at="2026-05-30T00:00:00+08:00",
                updated_at="2026-05-30T00:00:00+08:00",
            ),
            "## Summary\n\n- User likes structured practice.\n",
        )

        graph = build_wiki_graph(wiki_root)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "entity:user" in node_ids
        assert "concept:learning-style" in node_ids
        assert any(e["kind"] == "mentions_entity" for e in graph["edges"])
        assert any(e["kind"] == "mentions_concept" for e in graph["edges"])

    def test_taxonomy_projection_nodes_and_relation_edges(self, wiki_root: Path):
        from subagent.cross_session.wiki.processor.wiki_store import WikiStore

        store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
        store.apply_patch(
            WikiPatch(
                operation="merge_section",
                slug="entity/arsenal-supporter-profile",
                title="Arsenal Supporter Profile",
                type="entity",
                mode="freechat",
                section="Known Facts",
                content=(
                    "User's favorite football club is Arsenal.\n\n"
                    "Relations:\n"
                    "- user supports Arsenal"
                ),
                tags=[
                    "domain:sports",
                    "topic:football",
                    "subtype:favorite_team",
                    "entity:Arsenal",
                    "llm-extracted",
                ],
                topics=["sports/football"],
                links=[],
                sources=[WikiSource(kind="thread", session_id="s1", message_id="m4")],
                confidence="high",
            )
        )

        graph = build_wiki_graph(wiki_root)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "domain:sports" in node_ids
        assert "topic:sports/football" in node_ids
        assert "entity:Arsenal" in node_ids
        assert "entity:user" in node_ids
        assert "concept:sports/football/favorite_team" in node_ids

        edge_kinds = {e["kind"] for e in graph["edges"]}
        assert "has_domain" in edge_kinds
        assert "contains_topic" in edge_kinds
        assert "topic_entity" in edge_kinds
        assert "has_subtype" in edge_kinds
        assert "relation:supports" in edge_kinds

        graph_by_domain = build_wiki_graph(wiki_root, topic="sports")
        assert any(n["id"] == "entity/arsenal-supporter-profile" for n in graph_by_domain["nodes"])
