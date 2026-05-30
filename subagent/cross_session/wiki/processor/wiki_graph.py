"""WikiGraph - build graph data from wiki page metadata.

Graph structure:
  nodes: pages, tags, topics, modes
  edges: page->page (links), page->tag, page->topic, page->mode
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
                    size=1,
                )
            )

        # Link edges (page to page)
        for link in meta.links:
            edges.append(WikiGraphEdge(source=page_id, target=link, kind="link"))

        # Tag nodes and edges
        for tag in meta.tags:
            tag_id = f"tag:{tag}"
            if tag_id not in seen_node_ids:
                seen_node_ids.add(tag_id)
                nodes.append(WikiGraphNode(id=tag_id, label=tag, kind="tag", size=1))
            edges.append(WikiGraphEdge(source=page_id, target=tag_id, kind="has_tag"))

        # Topic nodes and edges
        for topic_val in meta.topics:
            topic_id = f"topic:{topic_val}"
            if topic_id not in seen_node_ids:
                seen_node_ids.add(topic_id)
                nodes.append(WikiGraphNode(id=topic_id, label=topic_val, kind="topic", size=1))
            edges.append(WikiGraphEdge(source=page_id, target=topic_id, kind="has_topic"))

        # Mode node and edge
        mode_id = f"mode:{meta.mode}"
        if mode_id not in seen_node_ids:
            seen_node_ids.add(mode_id)
            nodes.append(WikiGraphNode(id=mode_id, label=meta.mode, kind="mode", size=1))
        edges.append(WikiGraphEdge(source=page_id, target=mode_id, kind="has_mode"))

    return {
        "nodes": [n.to_dict() for n in nodes],
        "edges": [e.to_dict() for e in edges],
    }
