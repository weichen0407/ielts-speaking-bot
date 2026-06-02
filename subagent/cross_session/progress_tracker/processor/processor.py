"""ProgressTrackerProcessor - extracts progress highlights from user responses."""

from pathlib import Path

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line
from .schema import ProgressTrackerInput, ProgressTrackerOutput


class ProgressTrackerProcessor(BaseDataProcessor[ProgressTrackerInput, ProgressTrackerOutput]):
    """Progress Tracker 处理器 - 从用户回复中提取学习进步点"""

    name = "progress_tracker"

    def get_input_schema(self) -> type[ProgressTrackerInput]:
        return ProgressTrackerInput

    def get_output_schema(self) -> type[ProgressTrackerOutput]:
        return ProgressTrackerOutput

    def get_system_prompt(self) -> str:
        return r"""You are a progress tracker analyzing user responses.
Given user's conversation content, extract meaningful highlights worth tracking for progress.

Output format: tab-separated fields, one per line.

Format: category	intent	expression	content

Categories:
- emotion: 情感表达
- preference: 偏好
- habit: 习惯
- opinion: 观点
- experience: 经历
- goal: 目标
- description: 描述

Intents:
- positive: 积极表达
- negative: 消极表达
- neutral: 中性表达

Expression: The key phrase/expression used
Content: The original user content

Example:
preference	positive	I really enjoy	I really enjoy playing basketball on weekends
emotion	positive	feel grateful	I feel grateful for having supportive friends

If no meaningful content, output (none)."""

    def build_user_prompt(self, data: list[ProgressTrackerInput]) -> str:
        lines = []
        for item in data:
            if item.role == "user":
                topic = f"[{item.topic}]" if item.topic else ""
                lines.append(f"{topic} {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[ProgressTrackerOutput]:
        """解析 LLM 输出（第二工程层）"""
        results = []
        field_names = ["category", "intent", "expression", "content"]

        for line in raw_output.strip().split("\n"):
            line = line.strip()
            if not line or line == "(none)":
                continue

            parsed = parse_tab_line(line, len(field_names))
            if parsed and len(parsed) >= 3:
                results.append(ProgressTrackerOutput(**dict(zip(field_names, parsed))))
        return results

    def to_md(self, parsed_data: list[ProgressTrackerOutput]) -> str:
        """生成 Progress MD 格式"""
        if not parsed_data:
            return "# Progress Tracker\n\n(none)\n"

        lines = ["# Progress Tracker", ""]
        for i, item in enumerate(parsed_data, 1):
            lines.append(f"## {i}. {item.expression}")
            lines.append(f"- **类别**: {item.category}")
            lines.append(f"- **意图**: {item.intent}")
            lines.append(f"- **原文**: {item.content}")
            lines.append("")
        return "\n".join(lines)
