"""WikiGraph - build user-facing knowledge graph data.

Graph structure:
  nodes: topic clusters, wiki pages, entities, concepts
  edges: page->page links, page->topic membership, page->entity/concept mentions

Schema-only governance nodes such as type/tag/mode are intentionally omitted
from this graph. They remain in wiki metadata/search filters, but the visual
graph should show knowledge relationships instead of wiki internals.
"""

from __future__ import annotations

from pathlib import Path

from .schema import WikiPageMeta
from .wiki_store import WikiStore


class WikiGraphNode:
    def __init__(
        self,
        id: str,
        label: str,
        kind: str,
        *,
        type: str | None = None,
        mode: str | None = None,
        tags: list[str] | None = None,
        topics: list[str] | None = None,
        updated_at: str | None = None,
        summary: str | None = None,
        size: int = 1,
    ):
        self.id = id
        self.label = label
        self.kind = kind
        self.type = type
        self.mode = mode
        self.tags = tags or []
        self.topics = topics or []
        self.updated_at = updated_at
        self.summary = summary
        self.size = size

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "type": self.type,
            "mode": self.mode,
            "tags": self.tags,
            "topics": self.topics,
            "updated_at": self.updated_at,
            "summary": self.summary,
            "size": self.size,
        }


class WikiGraphEdge:
    def __init__(self, source: str, target: str, kind: str):
        self.source = source
        self.target = target
        self.kind = kind

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
        }


def build_wiki_graph(
    wiki_root: Path,
    *,
    mode: str | None = None,
    topic: str | None = None,
    page_type: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Build graph data from wiki pages.

    Returns {"nodes": [...], "edges": [...]} suitable for WebUI graph rendering.
    """
    store = WikiStore(workspace=wiki_root.parent, wiki_root=wiki_root)
    pages = store.list_pages()

    nodes: list[WikiGraphNode] = []
    edges: list[WikiGraphEdge] = []
    seen_node_ids: set[str] = set()

    for meta in pages:
        # Apply filters
        if mode and meta.mode != mode:
            continue
        if page_type and meta.type != page_type:
            continue
        if topic and topic not in meta.topics:
            continue
        if tags and not any(t in meta.tags for t in tags):
            continue

        page_id = meta.slug
        page_topics = meta.topics or [_fallback_topic(meta)]

        # Page node
        if page_id not in seen_node_ids:
            seen_node_ids.add(page_id)
            nodes.append(
                WikiGraphNode(
                    id=page_id,
                    label=meta.title,
                    kind="page",
                    type=meta.type,
                    mode=meta.mode,
                    tags=meta.tags,
                    topics=meta.topics,
                    updated_at=meta.updated_at,
                    size=max(1, len(meta.links) + len(meta.entities) + len(meta.concepts)),
                )
            )

        # Link edges (page to page)
        for link in meta.links:
            edges.append(WikiGraphEdge(source=page_id, target=link, kind="link"))

        # Topic cluster nodes and edges. Topics are intentionally large because
        # IELTS/freechat browsing should be organized around accumulated topics.
        for topic_val in page_topics:
            topic_id = f"topic:{topic_val}"
            if topic_id not in seen_node_ids:
                seen_node_ids.add(topic_id)
                nodes.append(
                    WikiGraphNode(
                        id=topic_id,
                        label=topic_val,
                        kind="topic",
                        type="topic",
                        mode=meta.mode,
                        topics=[topic_val],
                        size=8,
                    )
                )
            edges.append(WikiGraphEdge(source=page_id, target=topic_id, kind="has_topic"))

        for entity in meta.entities:
            entity_id = f"entity:{entity}"
            if entity_id not in seen_node_ids:
                seen_node_ids.add(entity_id)
                nodes.append(WikiGraphNode(id=entity_id, label=entity, kind="entity", size=3))
            edges.append(WikiGraphEdge(source=page_id, target=entity_id, kind="mentions_entity"))

        for concept in meta.concepts:
            concept_id = f"concept:{concept}"
            if concept_id not in seen_node_ids:
                seen_node_ids.add(concept_id)
                nodes.append(WikiGraphNode(id=concept_id, label=concept, kind="concept", size=3))
            edges.append(WikiGraphEdge(source=page_id, target=concept_id, kind="mentions_concept"))

    return {
        "nodes": [n.to_dict() for n in nodes],
        "edges": [e.to_dict() for e in edges],
    }


def _fallback_topic(meta: WikiPageMeta) -> str:
    if meta.mode == "ielts":
        return "ielts/general"
    if meta.mode == "freechat":
        return "freechat/topics"
    if meta.mode == "global":
        return "personal"
    return f"{meta.mode}/general"
