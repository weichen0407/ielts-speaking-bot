"""PolisherProcessor - extracts grammar improvements from conversation."""

from ..base import BaseDataProcessor
from ..utils import parse_kv_pairs
from .schema import PolisherInput, PolisherOutput


class PolisherProcessor(BaseDataProcessor[PolisherInput, PolisherOutput]):
    """语法处理器 - 从对话中提取语法改进"""

    name = "polisher"

    def get_input_schema(self) -> type[PolisherInput]:
        return PolisherInput

    def get_output_schema(self) -> type[PolisherOutput]:
        return PolisherOutput

    def get_system_prompt(self) -> str:
        return """You are a grammar and polish expert.
Given user's conversation content (both user and assistant messages), extract grammar patterns and expressions that could be improved.
Output format: key=value pairs without colons, one per line.

Example:
original=i go school improved=i go to school grammar_rule=preposition usage explanation=need 'to' before school
original=he dont improved=he doesn't grammar_rule=contraction explanation=use doesn't for third person singular"""

    def build_user_prompt(self, data: list[PolisherInput]) -> str:
        lines = []
        for item in data:
            role = "用户" if item.role == "user" else "AI"
            lines.append(f"{role}: {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[PolisherOutput]:
        results = []
        for line in raw_output.strip().split("\n"):
            if not line.strip():
                continue
            kwargs = parse_kv_pairs(line)
            if "original" in kwargs and "improved" in kwargs:
                results.append(PolisherOutput(**kwargs))
        return results
