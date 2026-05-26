"""NotesProcessor Schemas."""

from pydantic import BaseModel


class NotesInput(BaseModel):
    """NotesProcessor 输入 Schema"""
    id: str | None = None
    role: str
    content: str
    topic: str | None = None
    mode: str | None = None


class NotesOutput(BaseModel):
    """NotesProcessor 输出 Schema

    LLM 输出格式（tab 分隔）：
    title\tcontent\tcategory\treference\tcontext
    """
    title: str
    content: str
    category: str
    reference: str | None = None
    context: str | None = None
