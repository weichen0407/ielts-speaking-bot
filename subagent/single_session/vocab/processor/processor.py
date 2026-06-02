"""VocabProcessor - extracts vocabulary improvements from conversation."""

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line, split_batch_items
from .schema import VocabInput, VocabOutput


class VocabProcessor(BaseDataProcessor[VocabInput, VocabOutput]):
    """词汇处理器 - 从对话中提取需要改进的词汇和表达"""

    name = "vocab"

    def get_input_schema(self) -> type[VocabInput]:
        return VocabInput

    def get_output_schema(self) -> type[VocabOutput]:
        return VocabOutput

    def get_system_prompt(self) -> str:
        return r"""You are a vocabulary analysis expert.
Given user's conversation content, extract words and expressions that need improvement.
Output format: tab-separated fields, one improvement per line.

Format: original\timproved\ttype\treason

Types:
- expression: 表达方式
- collocation: 搭配
- vocabulary: 词汇
- idiom: 习语

If no improvement needed for a message, output (none).

Example:
3 points	three-point shot	expression	在篮球语境中更专业
is good	is on fire	collocation	更生动的表达

---

ate rice	had dinner	collocation	更自然的表达"""

    def build_user_prompt(self, data: list[VocabInput]) -> str:
        lines = []
        for item in data:
            if item.role == "user":
                lines.append(f"用户说: {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[VocabOutput]:
        """解析 LLM 输出（第二工程层）"""
        results = []
        items = split_batch_items(raw_output)
        field_names = ["original", "improved", "type", "reason"]

        for item in items:
            lines = item.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line or line == "(none)":
                    continue
                parsed = parse_tab_line(line, len(field_names))
                if parsed and len(parsed) == len(field_names):
                    results.append(VocabOutput(**dict(zip(field_names, parsed))))
        return results

    def to_md(self, parsed_data: list[VocabOutput]) -> str:
        """生成 Vocab MD 格式"""
        if not parsed_data:
            return "# Vocab\n\n(none)\n"

        lines = ["# Vocab", ""]
        for i, item in enumerate(parsed_data, 1):
            lines.append(f"## {i}")
            lines.append(f"- **原文**: {item.original}")
            lines.append(f"- **提升**: {item.improved}")
            lines.append(f"- **类型**: {item.type}")
            lines.append(f"- **解释**: {item.reason}")
            lines.append("")
        return "\n".join(lines)
