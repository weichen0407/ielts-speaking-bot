"""NotesProcessor - processes and categorizes notes from conversation."""

import json

from ..base import BaseDataProcessor
from ..utils import parse_kv_pairs
from .schema import NotesInput, NotesOutput


class NotesProcessor(BaseDataProcessor[NotesInput, NotesOutput]):
    """笔记处理器 - 从对话中提取和组织笔记"""

    name = "notes"

    def get_input_schema(self) -> type[NotesInput]:
        return NotesInput

    def get_output_schema(self) -> type[NotesOutput]:
        return NotesOutput

    def get_system_prompt(self) -> str:
        return """You are a notes organization expert.
Given user's conversation content, extract important notes and organize them.
Output format: key=value pairs without colons, one per line.

Example:
content=User loves playing tennis summary=tennis hobby tags=["hobbies","sports"] category=personal
content=User studying AI summary=AI major tags=["education","career"] category=academic"""

    def build_user_prompt(self, data: list[NotesInput]) -> str:
        lines = []
        for item in data:
            if item.role == "user":
                lines.append(f"用户说: {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[NotesOutput]:
        results = []
        for line in raw_output.strip().split("\n"):
            if not line.strip():
                continue
            kwargs = parse_kv_pairs(line)
            if "content" in kwargs:
                if "tags" in kwargs and isinstance(kwargs["tags"], str):
                    try:
                        kwargs["tags"] = json.loads(kwargs["tags"])
                    except json.JSONDecodeError:
                        kwargs["tags"] = []
                if "summary" not in kwargs:
                    kwargs["summary"] = None
                if "category" not in kwargs:
                    kwargs["category"] = "general"
                results.append(NotesOutput(**kwargs))
        return results
