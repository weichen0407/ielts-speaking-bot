"""PolisherProcessor Schemas."""

from pydantic import BaseModel


class PolisherInput(BaseModel):
    """PolisherProcessor 输入 Schema"""
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None


class PolisherOutput(BaseModel):
    """PolisherProcessor 输出 Schema"""
    original: str
    improved: str
    grammar_rule: str
    explanation: str | None = None
