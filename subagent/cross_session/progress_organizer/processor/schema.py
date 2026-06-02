"""ProgressOrganizer Schemas."""

from pydantic import BaseModel


class ProgressOrganizerInput(BaseModel):
    """ProgressOrganizerProcessor 输入 Schema"""
    id: str | None = None
    role: str | None = None
    content: str | None = None
    topic: str | None = None
    category: str | None = None
    intent: str | None = None
    expression: str | None = None


class ProgressOrganizerOutput(BaseModel):
    """ProgressOrganizerProcessor 输出 Schema

    LLM 输出格式（tab 分隔）：
    category	intent	expression
    """
    category: str
    intent: str
    expression: str
