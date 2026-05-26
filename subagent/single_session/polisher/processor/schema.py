"""PolisherProcessor Schemas."""

from pydantic import BaseModel


class PolisherInput(BaseModel):
    """PolisherProcessor 输入 Schema"""
    id: str | None = None
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None


class PolisherOutput(BaseModel):
    """PolisherProcessor 输出 Schema

    LLM 输出格式（tab 分隔）：
    original\timproved\tgrammar_type\texplanation
    """
    original: str
    improved: str
    grammar_type: str
    explanation: str | None = None
