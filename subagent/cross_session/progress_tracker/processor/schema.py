"""ProgressTracker Schemas."""

from pydantic import BaseModel


class ProgressTrackerInput(BaseModel):
    """ProgressTrackerProcessor 输入 Schema"""
    id: str | None = None
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None


class ProgressTrackerOutput(BaseModel):
    """ProgressTrackerProcessor 输出 Schema

    LLM 输出格式（tab 分隔）：
    category	intent	expression	content
    """
    category: str
    intent: str
    expression: str
    content: str
