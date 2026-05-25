"""Entity Extractor - parses LLM output into structured entities and relations."""

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from .entity_store import Entity, Relation


@dataclass
class ExtractedEntity:
    """An entity extracted from LLM output."""
    label: str
    entity_type: str
    topics: list[str] = field(default_factory=list)


@dataclass
class ExtractedRelation:
    """A relation extracted from LLM output."""
    from_label: str
    to_label: str
    rel_type: str
    topics: list[str] = field(default_factory=list)


class EntityExtractor:
    """
    Parses LLM output into structured entities and relations.

    LLM Output Format (key=value pairs, no colons):
    ENTITY: Jerry, type=person, topics=sports,food
    ENTITY: 打排球, type=activity, topics=sports,hobbies
    RELATION: Jerry-likes-打排球, type=likes, topics=sports
    """

    ENTITY_PATTERN = re.compile(
        r"^ENTITY:\s*(.+?),\s*type=(.+?)(?:,\s*topics=(.+?))?$",
        re.IGNORECASE,
    )
    RELATION_PATTERN = re.compile(
        r"^RELATION:\s*(.+?)-(.+?)-(.+?),\s*type=(.+?)(?:,\s*topics=(.+?))?$",
        re.IGNORECASE,
    )

    def parse_line(self, line: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        """Parse a single line of LLM output."""
        entities = []
        relations = []

        line = line.strip()
        if not line:
            return entities, relations

        # Try ENTITY pattern
        entity_match = self.ENTITY_PATTERN.match(line)
        if entity_match:
            label, entity_type, topics_str = entity_match.groups()
            topics = self._parse_topics(topics_str)
            entities.append(ExtractedEntity(
                label=label.strip(),
                entity_type=entity_type.strip(),
                topics=topics,
            ))
            return entities, relations

        # Try RELATION pattern
        relation_match = self.RELATION_PATTERN.match(line)
        if relation_match:
            from_label, rel_type, to_label, type_str, topics_str = relation_match.groups()
            topics = self._parse_topics(topics_str)
            relations.append(ExtractedRelation(
                from_label=from_label.strip(),
                to_label=to_label.strip(),
                rel_type=type_str.strip(),
                topics=topics,
            ))
            return entities, relations

        return entities, relations

    def parse(self, llm_output: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        """Parse full LLM output into entities and relations."""
        all_entities = []
        all_relations = []

        for line in llm_output.strip().split("\n"):
            entities, relations = self.parse_line(line)
            all_entities.extend(entities)
            all_relations.extend(relations)

        return all_entities, all_relations

    def _parse_topics(self, topics_str: str | None) -> list[str]:
        """Parse comma-separated topics string."""
        if not topics_str:
            return []
        return [t.strip() for t in topics_str.split(",") if t.strip()]

    def extract_to_store(
        self,
        llm_output: str,
        store: "EntityStore",
    ) -> tuple[list[Entity], list[Relation]]:
        """
        Parse LLM output and add entities/relations to store.

        Returns list of newly created entities and relations.
        """
        entities, relations = self.parse(llm_output)

        created_entities = []
        created_relations = []

        # Track label -> entity_id mapping for relation creation
        label_to_id: dict[str, str] = {}

        # First pass: create entities
        for ext_entity in entities:
            entity, created = store.get_or_create_entity(
                label=ext_entity.label,
                entity_type=ext_entity.entity_type,
                topics=ext_entity.topics,
            )
            if created:
                created_entities.append(entity)
            label_to_id[ext_entity.label] = entity.id

        # Second pass: create relations
        for ext_relation in relations:
            from_id = label_to_id.get(ext_relation.from_label)
            to_id = label_to_id.get(ext_relation.to_label)

            if from_id and to_id:
                # Check if relation already exists
                existing = store.query_relations(
                    rel_type=ext_relation.rel_type,
                    from_id=from_id,
                    to_id=to_id,
                )
                if not existing:
                    relation = Relation.create(
                        from_id=from_id,
                        to_id=to_id,
                        rel_type=ext_relation.rel_type,
                        topics=ext_relation.topics,
                    )
                    store.add_relation(relation)
                    created_relations.append(relation)

        return created_entities, created_relations
