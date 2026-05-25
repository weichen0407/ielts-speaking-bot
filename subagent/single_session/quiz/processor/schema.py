"""QuizProcessor Schemas."""

from pydantic import BaseModel


class QuizInput(BaseModel):
    """QuizProcessor 输入 Schema"""
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None


class QuizOutput(BaseModel):
    """QuizProcessor 输出 Schema"""
    question: str
    answer: str
    topic: str
    difficulty: str
    options: list[str] | None = None
