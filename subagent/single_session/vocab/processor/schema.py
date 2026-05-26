"""VocabProcessor Schemas."""

from pydantic import BaseModel


class VocabInput(BaseModel):
    """VocabProcessor 输入 Schema"""
    id: str | None = None
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None


class VocabOutput(BaseModel):
    """VocabProcessor 输出 Schema

    LLM 输出格式（tab 分隔）：
    original\timproved\ttype\treason
    """
    original: str
    improved: str
    type: str
    reason: str
