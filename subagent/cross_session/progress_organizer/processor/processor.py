"""ProgressOrganizerProcessor - refines and organizes progress entries."""

from pathlib import Path

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line
from .schema import ProgressOrganizerInput, ProgressOrganizerOutput


class ProgressOrganizerProcessor(BaseDataProcessor[ProgressOrganizerInput, ProgressOrganizerOutput]):
    """Progress Organizer 处理器 - 精炼和组织 progress entries"""

    name = "progress_organizer"

    def get_input_schema(self) -> type[ProgressOrganizerInput]:
        return ProgressOrganizerInput

    def get_output_schema(self) -> type[ProgressOrganizerOutput]:
        return ProgressOrganizerOutput

    def get_system_prompt(self) -> str:
        return r"""You are a progress organizer refining user expressions.
Given user expressions from progress tracking, refine category/intent, deduplicate, and merge similar expressions.

Output format: tab-separated fields, one per line.

Format: category	intent	expression

Categories:
- emotion: Feelings, attitudes, preferences, likes/dislikes
- description: Describing people, places, things, situations
- experience: Past events, stories, memories
- habit: Routines, regular activities
- opinion: Beliefs, views, judgments
- goal: Future plans, aspirations
- comparison: Comparing things
- cause: Reasons, explanations

Intents:
- positive: 积极表达
- negative: 消极表达
- neutral: 中性表达

Example:
emotion	positive	be fond of
description	neutral	weekend routine
opinion	positive	growth mindset

If no content to process, output (none)."""

    def build_user_prompt(self, data: list[ProgressOrganizerInput]) -> str:
        lines = []
        for item in data:
            if item.expression:
                lines.append(f"{item.expression}")
            elif item.role == "user":
                lines.append(f"{item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[ProgressOrganizerOutput]:
        """解析 LLM 输出（第二工程层）"""
        results = []
        field_names = ["category", "intent", "expression"]

        for line in raw_output.strip().split("\n"):
            line = line.strip()
            if not line or line == "(none)":
                continue

            parsed = parse_tab_line(line, len(field_names))
            if parsed and len(parsed) >= 3:
                results.append(ProgressOrganizerOutput(**dict(zip(field_names, parsed))))
        return results

    def to_md(self, parsed_data: list[ProgressOrganizerOutput]) -> str:
        """生成 Progress Organizer MD 格式"""
        if not parsed_data:
            return "# Progress Organizer\n\n(none)\n"

        lines = ["# Progress Organizer", ""]
        for i, item in enumerate(parsed_data, 1):
            lines.append(f"## {i}. {item.expression}")
            lines.append(f"- **类别**: {item.category}")
            lines.append(f"- **意图**: {item.intent}")
            lines.append("")
        return "\n".join(lines)
