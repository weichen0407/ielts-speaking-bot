"""VocabProcessor Schemas."""

from pydantic import BaseModel


class VocabInput(BaseModel):
    """VocabProcessor 输入 Schema"""
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None


class VocabOutput(BaseModel):
    """VocabProcessor 输出 Schema"""
    original: str
    improved: str
    word_type: str
    notes: str | None = None
