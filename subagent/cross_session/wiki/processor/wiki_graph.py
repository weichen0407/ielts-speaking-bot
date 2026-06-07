"""WikiGraph - build user-facing knowledge graph data.

Graph structure:
  nodes: domains, topic clusters, wiki pages, entities, concepts
  edges: page links, page-topic membership, taxonomy hierarchy, entity relations

Schema-only governance nodes such as raw page type/tag/mode are intentionally
omitted. They remain in wiki metadata/search filters, while the visual graph
shows knowledge relationships.
"""

from __future__ import annotations

import re
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
        memory_status: str | None = None,
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
        self.memory_status = memory_status
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
            "memory_status": self.memory_status,
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
    memory_status: str | None = None,
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
        if mode and meta.mode != mode:
            continue
        if page_type and meta.type != page_type:
            continue
        if topic and not _matches_topic_filter(meta, topic):
            continue
        if tags and not any(t in meta.tags for t in tags):
            continue
        if memory_status and not _matches_memory_status(meta.memory_status, memory_status):
            continue

        page_data = store.read_page(meta.slug)
        body = page_data[1] if page_data else ""
        projection = _taxonomy_from_meta(meta)
        page_id = meta.slug
        page_topics = meta.topics or [_fallback_topic(meta)]

        _add_node(
            nodes,
            seen_node_ids,
            WikiGraphNode(
                id=page_id,
                label=meta.title,
                kind="page",
                type=meta.type,
                mode=meta.mode,
                tags=meta.tags,
                topics=meta.topics,
                updated_at=meta.updated_at,
                memory_status=meta.memory_status,
                size=max(
                    1,
                    len(meta.links)
                    + len(meta.entities)
                    + len(meta.concepts)
                    + len(projection.entities),
                ),
            ),
        )

        _add_taxonomy_nodes(nodes, edges, seen_node_ids, meta, page_id, projection)

        for link in meta.links:
            edges.append(WikiGraphEdge(source=page_id, target=link, kind="link"))

        for topic_val in page_topics:
            if projection.topic_path and topic_val == projection.topic_path:
                continue
            topic_id = f"topic:{topic_val}"
            _add_node(
                nodes,
                seen_node_ids,
                WikiGraphNode(
                    id=topic_id,
                    label=topic_val,
                    kind="topic",
                    type="topic",
                    mode=meta.mode,
                    topics=[topic_val],
                    size=8,
                ),
            )
            edges.append(WikiGraphEdge(source=page_id, target=topic_id, kind="has_topic"))

        all_entities = _unique([*meta.entities, *projection.entities])
        for entity in all_entities:
            entity_id = f"entity:{entity}"
            _add_node(
                nodes,
                seen_node_ids,
                WikiGraphNode(id=entity_id, label=_human_label(entity), kind="entity", size=4),
            )
            edges.append(WikiGraphEdge(source=page_id, target=entity_id, kind="mentions_entity"))
            if projection.topic_path:
                edges.append(WikiGraphEdge(source=f"topic:{projection.topic_path}", target=entity_id, kind="topic_entity"))

        for concept in meta.concepts:
            concept_id = f"concept:{concept}"
            _add_node(
                nodes,
                seen_node_ids,
                WikiGraphNode(id=concept_id, label=_human_label(concept), kind="concept", size=3),
            )
            edges.append(WikiGraphEdge(source=page_id, target=concept_id, kind="mentions_concept"))

        for source, predicate, target in _relations_from_body(body):
            source_id = f"entity:{source}"
            target_id = f"entity:{target}"
            _add_node(
                nodes,
                seen_node_ids,
                WikiGraphNode(id=source_id, label=_human_label(source), kind="entity", size=5),
            )
            _add_node(
                nodes,
                seen_node_ids,
                WikiGraphNode(id=target_id, label=_human_label(target), kind="entity", size=4),
            )
            edges.append(WikiGraphEdge(source=source_id, target=target_id, kind=f"relation:{predicate}"))
            edges.append(WikiGraphEdge(source=page_id, target=source_id, kind="mentions_entity"))
            edges.append(WikiGraphEdge(source=page_id, target=target_id, kind="mentions_entity"))

    return {
        "nodes": [n.to_dict() for n in nodes],
        "edges": [e.to_dict() for e in edges],
    }


class _TaxonomyProjection:
    def __init__(
        self,
        *,
        domain: str | None = None,
        topic: str | None = None,
        subtype: str | None = None,
        entities: list[str] | None = None,
    ) -> None:
        self.domain = domain
        self.topic = topic
        self.subtype = subtype
        self.entities = entities or []

    @property
    def topic_path(self) -> str | None:
        if self.domain and self.topic:
            return f"{self.domain}/{self.topic}"
        return self.topic


def _add_taxonomy_nodes(
    nodes: list[WikiGraphNode],
    edges: list[WikiGraphEdge],
    seen_node_ids: set[str],
    meta: WikiPageMeta,
    page_id: str,
    projection: _TaxonomyProjection,
) -> None:
    if projection.domain:
        domain_id = f"domain:{projection.domain}"
        _add_node(
            nodes,
            seen_node_ids,
            WikiGraphNode(
                id=domain_id,
                label=_human_label(projection.domain),
                kind="domain",
                type="domain",
                mode=meta.mode,
                topics=[projection.domain],
                size=12,
            ),
        )
        edges.append(WikiGraphEdge(source=page_id, target=domain_id, kind="has_domain"))

    if projection.topic:
        topic_path = projection.topic_path or projection.topic
        topic_id = f"topic:{topic_path}"
        _add_node(
            nodes,
            seen_node_ids,
            WikiGraphNode(
                id=topic_id,
                label=_human_label(projection.topic),
                kind="topic",
                type="topic",
                mode=meta.mode,
                topics=[topic_path],
                size=9,
            ),
        )
        edges.append(WikiGraphEdge(source=page_id, target=topic_id, kind="has_topic"))
        if projection.domain:
            edges.append(WikiGraphEdge(source=f"domain:{projection.domain}", target=topic_id, kind="contains_topic"))

    if projection.subtype:
        subtype_topic = projection.topic_path or projection.domain or "taxonomy"
        subtype_id = f"concept:{subtype_topic}/{projection.subtype}"
        _add_node(
            nodes,
            seen_node_ids,
            WikiGraphNode(
                id=subtype_id,
                label=_human_label(projection.subtype),
                kind="concept",
                type="subtype",
                mode=meta.mode,
                topics=[projection.topic_path] if projection.topic_path else [],
                size=3,
            ),
        )
        edges.append(WikiGraphEdge(source=page_id, target=subtype_id, kind="has_subtype"))


def _add_node(nodes: list[WikiGraphNode], seen_node_ids: set[str], node: WikiGraphNode) -> None:
    if node.id in seen_node_ids:
        return
    seen_node_ids.add(node.id)
    nodes.append(node)


def _taxonomy_from_meta(meta: WikiPageMeta) -> _TaxonomyProjection:
    domain = _tag_value(meta.tags, "domain:")
    topic = _tag_value(meta.tags, "topic:")
    subtype = _tag_value(meta.tags, "subtype:")
    entities = [tag[len("entity:"):] for tag in meta.tags if tag.startswith("entity:")]

    if not domain or not topic:
        for topic_val in meta.topics:
            if "/" not in topic_val:
                continue
            left, right = topic_val.split("/", 1)
            domain = domain or left
            topic = topic or right
            break

    return _TaxonomyProjection(
        domain=domain,
        topic=topic,
        subtype=subtype,
        entities=_unique(entities),
    )


def _matches_topic_filter(meta: WikiPageMeta, topic: str) -> bool:
    if topic in meta.topics:
        return True
    projection = _taxonomy_from_meta(meta)
    return topic in {projection.domain, projection.topic, projection.topic_path}


def _matches_memory_status(actual: str, wanted: str) -> bool:
    wanted = wanted.strip().lower()
    actual = (actual or "new").strip().lower()
    if wanted == "uncertain":
        return actual in {"new", "needs_user_confirmation", "contradicted"}
    if wanted == "confirmed":
        return actual == "confirmed"
    if wanted == "stale":
        return actual == "stale"
    return actual == wanted


def _tag_value(tags: list[str], prefix: str) -> str | None:
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


def _relations_from_body(body: str) -> list[tuple[str, str, str]]:
    relations: list[tuple[str, str, str]] = []
    in_relations = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.rstrip(":").lower() == "relations":
            in_relations = True
            continue
        if line.startswith("## ") and in_relations:
            break
        if not in_relations or not line.startswith("- "):
            continue
        relation = _parse_relation_line(line[2:].strip())
        if relation:
            relations.append(relation)
    return relations


def _parse_relation_line(text: str) -> tuple[str, str, str] | None:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return None
    match = re.match(r"(.+?)\s+([a-zA-Z_][\w-]*)\s+(.+)$", compact)
    if not match:
        return None
    source, predicate, target = match.groups()
    return (_normalize_entity(source), predicate, _normalize_entity(target))


def _normalize_entity(value: str) -> str:
    value = value.strip().strip(".")
    if value.lower() == "user":
        return "user"
    return value


def _human_label(value: str) -> str:
    if value.lower() == "user":
        return "User"
    text = value.replace("_", " ").replace("-", " ").replace("/", " / ")
    return " ".join(part.capitalize() if part.islower() else part for part in text.split())


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _fallback_topic(meta: WikiPageMeta) -> str:
    if meta.mode == "ielts":
        return "ielts/general"
    if meta.mode == "freechat":
        return "freechat/topics"
    if meta.mode == "global":
        return "personal"
    return f"{meta.mode}/general"
