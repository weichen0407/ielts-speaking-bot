"""NotesProcessor Schemas."""

from pydantic import BaseModel


class NotesInput(BaseModel):
    """NotesProcessor 输入 Schema"""
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None


class NotesOutput(BaseModel):
    """NotesProcessor 输出 Schema"""
    content: str
    category: str
    tags: list[str]
    summary: str | None = None
