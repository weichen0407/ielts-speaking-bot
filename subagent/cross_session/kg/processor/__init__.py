"""Knowledge Graph - entity storage and query.

DEPRECATED: This module is superseded by subagent.cross_session.wiki.
It is kept in place for reference only. Do not use for new development.
"""

from .entity_store import EntityStore, Entity, Relation
from .cursor import CursorManager, KG_Cursor
from .extractor import EntityExtractor, ExtractedEntity, ExtractedRelation
from .kg_updater import KGUpdater
from .topics import IELTS_TOPICS, ENTITY_TYPES, RELATION_TYPES
from .kg_processor import KGProcessor
from .schema import KGInput, KGOutput

__all__ = [
    "EntityStore",
    "Entity",
    "Relation",
    "CursorManager",
    "KG_Cursor",
    "EntityExtractor",
    "ExtractedEntity",
    "ExtractedRelation",
    "KGUpdater",
    "IELTS_TOPICS",
    "ENTITY_TYPES",
    "RELATION_TYPES",
    "KGProcessor",
    "KGInput",
    "KGOutput",
]
