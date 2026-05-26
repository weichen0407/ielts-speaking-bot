"""PolisherProcessor - extracts grammar improvements from conversation."""

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line, split_batch_items
from .schema import PolisherInput, PolisherOutput


class PolisherProcessor(BaseDataProcessor[PolisherInput, PolisherOutput]):
    """语法处理器 - 从对话中提取语法改进"""

    name = "polisher"

    def get_input_schema(self) -> type[PolisherInput]:
        return PolisherInput

    def get_output_schema(self) -> type[PolisherOutput]:
        return PolisherOutput

    def get_system_prompt(self) -> str:
        return r"""You are a grammar and polish expert.
Given user's conversation content, extract grammar patterns and expressions that could be improved.
Output format: tab-separated fields, one improvement per line.

Format: original\timproved\tgrammar_type\texplanation

Grammar types:
- verb_phrase: 动词短语
- article: 冠词
- preposition: 介词
- tense: 时态
- plural: 单复数
- word_order: 语序
- adjective: 形容词
- other: 其他

If no improvement needed for a message, output (none).

Example:
i go school	i go to school	preposition	需要加介词 to
he dont like	he doesn't like	verb_phrase	第三人称单数用 doesn't

---

she very like	she really likes	adjective	very 不能修饰动词，应该用 really"""

    def build_user_prompt(self, data: list[PolisherInput]) -> str:
        lines = []
        for item in data:
            if item.role == "user":
                lines.append(f"用户说: {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[PolisherOutput]:
        """解析 LLM 输出（第二工程层）"""
        results = []
        items = split_batch_items(raw_output)
        field_names = ["original", "improved", "grammar_type", "explanation"]

        for item in items:
            lines = item.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line or line == "(none)":
                    continue
                parsed = parse_tab_line(line, len(field_names))
                if parsed and len(parsed) >= 3:  # explanation is optional
                    results.append(PolisherOutput(**parsed))
        return results

    def to_md(self, parsed_data: list[PolisherOutput]) -> str:
        """生成 Polisher MD 格式"""
        if not parsed_data:
            return "# Polisher\n\n(none)\n"

        lines = ["# Polisher", ""]
        for i, item in enumerate(parsed_data, 1):
            lines.append(f"## {i}")
            lines.append(f"- **原文**: {item.original}")
            lines.append(f"- **提升**: {item.improved}")
            lines.append(f"- **语法类型**: {item.grammar_type}")
            if item.explanation:
                lines.append(f"- **解释**: {item.explanation}")
            lines.append("")
        return "\n".join(lines)
