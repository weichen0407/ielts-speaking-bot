"""VocabProcessor - extracts vocabulary improvements from conversation."""

from ..base import BaseDataProcessor
from ..utils import parse_kv_pairs
from .schema import VocabInput, VocabOutput


class VocabProcessor(BaseDataProcessor[VocabInput, VocabOutput]):
    """词汇处理器 - 从对话中提取需要改进的词汇和表达"""

    name = "vocab"

    def get_input_schema(self) -> type[VocabInput]:
        return VocabInput

    def get_output_schema(self) -> type[VocabOutput]:
        return VocabOutput

    def get_system_prompt(self) -> str:
        return """You are a vocabulary analysis expert.
Given user's conversation content, extract words and expressions that need improvement.
Output format: key=value pairs without colons, one per line.

Example:
original=i like humburgers improved=I'm quite fond of hamburgers word_type=expression notes=food preference
original=i study ai improved=I'm majoring in AI word_type=expression notes=education"""

    def build_user_prompt(self, data: list[VocabInput]) -> str:
        lines = []
        for item in data:
            if item.role == "user":
                lines.append(f"用户说: {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[VocabOutput]:
        results = []
        for line in raw_output.strip().split("\n"):
            if not line.strip():
                continue
            kwargs = parse_kv_pairs(line)
            if "original" in kwargs and "improved" in kwargs:
                results.append(VocabOutput(**kwargs))
        return results
