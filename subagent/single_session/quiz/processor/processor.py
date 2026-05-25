"""QuizProcessor - generates quiz questions from conversation."""

import json

from ..base import BaseDataProcessor
from ..utils import parse_kv_pairs
from .schema import QuizInput, QuizOutput


class QuizProcessor(BaseDataProcessor[QuizInput, QuizOutput]):
    """Quiz 处理器 - 从对话中生成 Quiz 题目"""

    name = "quiz"

    def get_input_schema(self) -> type[QuizInput]:
        return QuizInput

    def get_output_schema(self) -> type[QuizOutput]:
        return QuizOutput

    def get_system_prompt(self) -> str:
        return """You are a quiz question generator.
Given user's conversation content, generate quiz questions to test understanding.
Output format: key=value pairs without colons, one per line.

Example:
question=What topic did the user discuss? answer=hobbies topic=hobbies difficulty=easy options=["food","hobbies","travel"]
question=What is the user's opinion about tennis? answer=They love playing it topic=hobbies difficulty=medium options=["They love it","They hate it","They never play"]"""

    def build_user_prompt(self, data: list[QuizInput]) -> str:
        lines = []
        for item in data:
            if item.role == "user":
                topic = f" (topic: {item.topic})" if item.topic else ""
                lines.append(f"用户说{topic}: {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[QuizOutput]:
        results = []
        for line in raw_output.strip().split("\n"):
            if not line.strip():
                continue
            kwargs = parse_kv_pairs(line)
            if "question" in kwargs and "answer" in kwargs:
                if "options" in kwargs and isinstance(kwargs["options"], str):
                    try:
                        kwargs["options"] = json.loads(kwargs["options"])
                    except json.JSONDecodeError:
                        kwargs["options"] = None
                results.append(QuizOutput(**kwargs))
        return results
