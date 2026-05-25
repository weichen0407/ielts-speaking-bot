"""Entity Store - persistent storage for entities and relations."""

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import networkx as nx


@dataclass
class Entity:
    """A single entity in the knowledge graph."""
    id: str
    label: str
    type: str
    topics: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)

    @staticmethod
    def create(label: str, entity_type: str, topics: list[str] | None = None) -> "Entity":
        """Create a new entity with auto-generated ID."""
        return Entity(
            id=f"e{uuid.uuid4().hex[:8]}",
            label=label,
            type=entity_type,
            topics=topics or [],
            properties={},
        )


@dataclass
class Relation:
    """A relation between two entities."""
    id: str
    from_id: str
    to_id: str
    type: str
    topics: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)

    @staticmethod
    def create(from_id: str, to_id: str, rel_type: str, topics: list[str] | None = None) -> "Relation":
        """Create a new relation with auto-generated ID."""
        return Relation(
            id=f"r{uuid.uuid4().hex[:8]}",
            from_id=from_id,
            to_id=to_id,
            type=rel_type,
            topics=topics or [],
            properties={},
        )


class EntityStore:
    """
    Persistent storage for entities and relations.

    Uses NetworkX for graph operations and JSON for persistence.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.data_dir / "entity_database.json"
        self.entities: dict[str, Entity] = {}
        self.relations: dict[str, Relation] = {}
        self._graph: nx.MultiDiGraph | None = None
        self._load()

    def _load(self) -> None:
        """Load entities and relations from JSON file."""
        if not self.json_path.exists():
            return

        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.entities = {
            e["id"]: Entity(**e) for e in data.get("entities", [])
        }
        self.relations = {
            r["id"]: Relation(**r) for r in data.get("relations", [])
        }

    def save(self) -> None:
        """Save entities and relations to JSON file."""
        data = {
            "entities": [asdict(e) for e in self.entities.values()],
            "relations": [asdict(r) for r in self.relations.values()],
        }

        tmp_path = self.json_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        tmp_path.replace(self.json_path)

    def add_entity(self, entity: Entity) -> None:
        """Add a new entity."""
        self.entities[entity.id] = entity
        self._graph = None  # Invalidate graph cache

    def add_relation(self, relation: Relation) -> None:
        """Add a new relation."""
        self.relations[relation.id] = relation
        self._graph = None  # Invalidate graph cache

    def get_entity(self, entity_id: str) -> Entity | None:
        """Get entity by ID."""
        return self.entities.get(entity_id)

    def find_entity_by_label(self, label: str) -> Entity | None:
        """Find entity by label (exact match)."""
        for entity in self.entities.values():
            if entity.label == label:
                return entity
        return None

    def query_entities(
        self,
        entity_type: str | None = None,
        topics: list[str] | None = None,
    ) -> list[Entity]:
        """Query entities by type and/or topics."""
        results = list(self.entities.values())

        if entity_type:
            results = [e for e in results if e.type == entity_type]

        if topics:
            results = [e for e in results if any(t in e.topics for t in topics)]

        return results

    def query_relations(
        self,
        rel_type: str | None = None,
        topics: list[str] | None = None,
        from_id: str | None = None,
        to_id: str | None = None,
    ) -> list[Relation]:
        """Query relations by type, topics, or endpoints."""
        results = list(self.relations.values())

        if rel_type:
            results = [r for r in results if r.type == rel_type]

        if topics:
            results = [r for r in results if any(t in r.topics for t in topics)]

        if from_id:
            results = [r for r in results if r.from_id == from_id]

        if to_id:
            results = [r for r in results if r.to_id == to_id]

        return results

    def get_or_create_entity(
        self,
        label: str,
        entity_type: str,
        topics: list[str] | None = None,
    ) -> tuple[Entity, bool]:
        """
        Get existing entity or create new one.

        Returns (entity, created) where created is True if new entity was created.
        """
        existing = self.find_entity_by_label(label)
        if existing:
            # Merge topics if entity exists
            if topics:
                for topic in topics:
                    if topic not in existing.topics:
                        existing.topics.append(topic)
            return existing, False

        entity = Entity.create(label, entity_type, topics)
        self.add_entity(entity)
        return entity, True

    def get_graph(self) -> nx.MultiDiGraph:
        """Get NetworkX graph representation."""
        if self._graph is None:
            self._graph = nx.MultiDiGraph()
            for entity in self.entities.values():
                self._graph.add_node(entity.id, **asdict(entity))
            for relation in self.relations.values():
                self._graph.add_edge(
                    relation.from_id,
                    relation.to_id,
                    **asdict(relation),
                )
        return self._graph

    def get_related_entities(
        self,
        entity_id: str,
        max_depth: int = 1,
    ) -> list[tuple[Entity, Relation]]:
        """Get entities related to the given entity."""
        graph = self.get_graph()
        if entity_id not in graph:
            return []

        results = []
        for neighbor in graph.neighbors(entity_id):
            edge_data = graph.get_edge_data(entity_id, neighbor)
            related_entity = self.entities.get(neighbor)
            if related_entity and edge_data:
                for edge in edge_data.values():
                    results.append((related_entity, Relation(**edge)))
        return results

    def to_dict(self) -> dict[str, Any]:
        """Return as dictionary for serialization."""
        return {
            "entities": [asdict(e) for e in self.entities.values()],
            "relations": [asdict(r) for r in self.relations.values()],
        }
