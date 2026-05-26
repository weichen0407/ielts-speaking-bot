"""QuizProcessor - generates quiz questions from review points."""

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line, split_batch_items
from .schema import QuizInput, QuizOutput


class QuizProcessor(BaseDataProcessor[QuizInput, QuizOutput]):
    """Quiz 处理器 - 从复习点生成Quiz题目"""

    name = "quiz"

    def get_input_schema(self) -> type[QuizInput]:
        return QuizInput

    def get_output_schema(self) -> type[QuizOutput]:
        return QuizOutput

    def get_system_prompt(self) -> str:
        return r"""You are a quiz question generator.
Given review points extracted from user's learning content, generate quiz questions to test understanding.

Output format: tab-separated fields, one question per line.

Format: question\tanswer\tdifficulty\ttopic

Difficulty levels:
- beginner: Simple vocabulary recall
- intermediate: Application in context
- advanced: Creative/use in complex sentences

Question types (based on question_type hint):
- sentence_use: "Please use '{review_point}' in a sentence"
- translation: "Translate: {review_point_in_chinese}"
- correction: "Correct if needed: {review_point}"
- explanation: "Explain the difference: {review_point}"

If no question can be generated, output (none).

Example input:
be fond of	sentence_use	3	hobbies

Example output:
Please use "be fond of" in a sentence about your hobbies.	I'm quite fond of collecting vintage sneakers.	intermediate	hobbies

---

excellent	correction	4	null

Example output:
Correct this sentence if needed: "This restaurant has excellent food."	Excellent is already correct here, no correction needed.	beginner	null"""

    def build_user_prompt(self, data: list[QuizInput]) -> str:
        lines = []
        for item in data:
            q_type = item.question_type or "sentence_use"
            topic = f"[{item.topic}]" if item.topic else ""
            lines.append(f"{item.review_point}\t{q_type}\t{item.familiarity_hint or 3}\t{topic}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[QuizOutput]:
        """解析 LLM 输出（第二工程层）"""
        results = []
        items = split_batch_items(raw_output)
        field_names = ["question", "answer", "difficulty", "topic"]

        for item in items:
            lines = item.strip().split("\n")
            for line in lines:
                line = line.strip()
                if not line or line == "(none)":
                    continue
                parsed = parse_tab_line(line, len(field_names))
                if parsed and len(parsed) >= 3:  # topic is optional
                    results.append(QuizOutput(**parsed))
        return results

    def to_md(self, parsed_data: list[QuizOutput]) -> str:
        """生成 Quiz MD 格式"""
        if not parsed_data:
            return "# Quiz\n\n(none)\n"

        lines = ["# Quiz", ""]
        for i, item in enumerate(parsed_data, 1):
            lines.append(f"## {i}")
            lines.append(f"- **题目**: {item.question}")
            lines.append(f"- **答案**: {item.answer}")
            lines.append(f"- **难度**: {item.difficulty}")
            if item.topic:
                lines.append(f"- **话题**: {item.topic}")
            lines.append("")
        return "\n".join(lines)
