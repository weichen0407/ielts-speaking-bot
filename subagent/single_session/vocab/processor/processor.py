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
        return r"""You are the vocab subagent for freechat English learning.
Your job is lexical-resource improvement only: stronger words, phrases, collocations, idioms, register, and topic vocabulary.

Do NOT correct grammar, tense, word order, or sentence structure unless the improvement is strictly lexical.
Do NOT rewrite whole answers. Keep each item focused on one vocabulary or phrase improvement.

Output tab-separated fields, one improvement per line:

Format: original\timproved\ttype\treason

Allowed types:
- word_choice: weak/general word -> more precise word
- collocation: unnatural word combination -> natural collocation
- phrase: simple phrase -> more natural phrase
- topic_vocabulary: topic-specific lexical upgrade
- idiom: suitable idiomatic expression
- register: casual/formal/register improvement

If no lexical improvement is useful, output (none).

Examples:
good	memorable	word_choice	更具体，适合描述电影或经历
very interesting	thought-provoking	collocation	更自然且更高级的评价表达
talk about movies	discuss films	phrase	更简洁、更偏学习场景的表达
cheap restaurant	budget-friendly restaurant	register	更自然且语气更礼貌"""

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
