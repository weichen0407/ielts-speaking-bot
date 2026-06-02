"""NotesProcessor - captures expressions user didn't know how to say."""

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line, split_batch_items
from .schema import NotesInput, NotesOutput


class NotesProcessor(BaseDataProcessor[NotesInput, NotesOutput]):
    """笔记处理器 - 捕获用户不会表达的内容"""

    name = "notes"

    def get_input_schema(self) -> type[NotesInput]:
        return NotesInput

    def get_output_schema(self) -> type[NotesOutput]:
        return NotesOutput

    def get_system_prompt(self) -> str:
        return r"""You are a notes organization expert.
Your task is to identify moments in the conversation where the user didn't know how to express something, or asked for clarification on how to say something properly.

Look for patterns like:
- User asking "how do you say..."
- User saying "what's the word for..."
- User struggling to express an idea
- User asking "is there a better way to say..."
- User making grammar mistakes and getting corrected

For each note-worthy moment, extract:
1. title: What the user wanted to know (e.g., "三分球怎么说")
2. content: The proper way to express it (the answer learned)
3. category: vocabulary | grammar | idiom | expression | other
4. reference: The user's original message (what they were trying to say)
5. context: Brief explanation of when to use this expression

Output format: tab-separated fields, one note per line.

If no notable expressions found for a message, output (none).

Example:
三分球怎么说	three-point shot	vocabulary	"3 points is good"	在篮球语境中使用
防守怎么说	play defense	vocabulary	"how to say defense"	讨论篮球战术

---

怎么形容一个人很火	be on fire	idiom	"is very hot"	形容状态火热"""

    def build_user_prompt(self, data: list[NotesInput]) -> str:
        lines = []
        for item in data:
            if item.role == "user":
                lines.append(f"用户: {item.content}")
                if item.topic:
                    lines.append(f"话题: {item.topic}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[NotesOutput]:
        """解析 LLM 输出（第二工程层）"""
        results = []
        items = split_batch_items(raw_output)
        field_names = ["title", "content", "category", "reference", "context"]

        for item in items:
            lines = item.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line or line == "(none)":
                    continue
                parsed = parse_tab_line(line, len(field_names), min_fields=2)
                if parsed and len(parsed) >= 2:
                    # reference and context are optional
                    results.append(NotesOutput(**dict(zip(field_names, parsed))))
        return results

    def to_md(self, parsed_data: list[NotesOutput]) -> str:
        """生成 Notes MD 格式"""
        if not parsed_data:
            return "# Notes\n\n(none)\n"

        # Group by topic or category
        lines = ["# Notes", ""]

        for i, item in enumerate(parsed_data, 1):
            lines.append(f"## {i}. {item.title}")
            lines.append(f"- **分类**: {item.category}")
            lines.append(f"- **内容**: {item.content}")
            if item.reference:
                lines.append(f"- **参考**: \"{item.reference}\"")
            if item.context:
                lines.append(f"- **上下文**: {item.context}")
            lines.append("")
        return "\n".join(lines)
