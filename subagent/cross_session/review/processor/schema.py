"""ReviewProcessor Schemas."""

from pydantic import BaseModel


class ReviewInput(BaseModel):
    """ReviewProcessor 输入 Schema"""
    id: str | None = None
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None
    source: str | None = None  # e.g., "vocab", "polisher", "notes"


class ReviewOutput(BaseModel):
    """ReviewProcessor 输出 Schema

    LLM 输出格式（tab 分隔）：
    review_point	question_type	familiarity_hint	topic
    """
    review_point: str
    question_type: str
    familiarity_hint: int
    topic: str | None = None
