"""QuizProcessor Schemas."""

from pydantic import BaseModel


class QuizInput(BaseModel):
    """QuizProcessor 输入 Schema"""
    id: str | None = None
    review_point: str
    question_type: str
    familiarity_hint: int | None = None
    topic: str | None = None


class QuizOutput(BaseModel):
    """QuizProcessor 输出 Schema

    LLM 输出格式（tab 分隔）：
    question\tanswer\tdifficulty\ttopic
    """
    question: str
    answer: str
    difficulty: str
    topic: str | None = None
