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

    def _filter_fields(self, item: dict) -> dict:
        """Adapt both thread events and Be Native response events."""
        result = super()._filter_fields(item)
        if "user_en" in item and "content" not in result:
            result["content"] = item.get("user_en", "")
            result["role"] = "user"
        if "article_id" in item and "topic" not in result:
            result["topic"] = item.get("article_id")
        if "mode" not in result and "user_en" in item:
            result["mode"] = "benative"
        return result

    def get_system_prompt(self) -> str:
        return r"""You are the polisher subagent for freechat English learning.
Your job is sentence-level improvement: grammar, sentence structure, word order, natural phrasing, fluency, coherence, and spoken-English clarity.

Do not output isolated vocabulary upgrades unless they are part of a sentence-level rewrite.
Do not score the user. Do not produce long coaching paragraphs.

Output tab-separated fields, one improvement per line:

Format: original\timproved\tgrammar_type\texplanation

Allowed grammar_type values:
- grammar: general grammar correction
- sentence_structure: clearer or more complex sentence structure
- word_order: unnatural order -> natural order
- tense: tense or aspect improvement
- article: a/an/the or zero article
- preposition: missing or incorrect preposition
- natural_expression: awkward phrase -> natural spoken English
- coherence: smoother connection between ideas
- other: useful sentence-level polish that does not fit above

If no sentence-level improvement is useful, output (none).

Examples:
i go school	i go to school	preposition	需要加介词 to
he dont like	he doesn't like	grammar	第三人称单数和否定形式需要调整
I like play basketball	I like playing basketball	grammar	like 后接动名词更自然
I want go to Paris watch football	I want to go to Paris to watch a football match	sentence_structure	补全不定式结构，让句子更清晰自然"""

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
                parsed = parse_tab_line(line, len(field_names), min_fields=3)
                if parsed and len(parsed) >= 3:  # explanation is optional
                    results.append(PolisherOutput(**dict(zip(field_names, parsed))))
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
