"""KGProcessor Schemas."""

from pydantic import BaseModel


class KGInput(BaseModel):
    """KGProcessor 输入 Schema"""
    id: str | None = None
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None
    source: str | None = None  # e.g., "vocab", "polisher", "notes"


class KGOutput(BaseModel):
    """KGProcessor 输出 Schema

    LLM 输出格式（tab 分隔）：
    label	entity_type	topics (entity)
    或
    from_label	to_label	relation_type	topics (relation)
    """
    # Entity output
    label: str | None = None
    entity_type: str | None = None
    topics: str | None = None

    # Relation output
    from_label: str | None = None
    to_label: str | None = None
    relation_type: str | None = None

    # Parsed topics as list
    topics_list: list[str] = []

    @property
    def is_entity(self) -> bool:
        return self.label is not None and self.entity_type is not None

    @property
    def is_relation(self) -> bool:
        return self.from_label is not None and self.to_label is not None
