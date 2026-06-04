"""BenativeReviewProcessor - evaluates reconstruction answers."""

from __future__ import annotations

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line, split_batch_items

from .schema import BenativeReviewInput, BenativeReviewOutput


class BenativeReviewProcessor(BaseDataProcessor[BenativeReviewInput, BenativeReviewOutput]):
    """Compare user answers with the standard English sentence."""

    name = "benative_review"

    def get_input_schema(self) -> type[BenativeReviewInput]:
        return BenativeReviewInput

    def get_output_schema(self) -> type[BenativeReviewOutput]:
        return BenativeReviewOutput

    def get_system_prompt(self) -> str:
        return r"""You are the benative_review subagent.
Evaluate a user's English reconstruction against the standard English sentence.

Return only tab-separated rows.

Format:
article_id	sentence_index	accuracy_score	naturalness_score	issue_type	user_en	standard_en	suggested_en	feedback

Scoring:
- accuracy_score: 0-100, meaning preservation
- naturalness_score: 0-100, native-like expression

Issue types:
- meaning
- grammar
- vocabulary
- collocation
- word_order
- missing_detail
- entity
- natural_expression
- excellent
- other

Feedback should be concise Chinese, with one actionable suggestion.
If the answer is already excellent, use issue_type excellent and still provide a reusable pattern."""

    def build_user_prompt(self, data: list[BenativeReviewInput]) -> str:
        lines: list[str] = []
        for item in data:
            lines.append(f"ARTICLE_ID: {item.article_id}")
            lines.append(f"SENTENCE_INDEX: {item.sentence_index}")
            lines.append(f"ZH_PROMPT: {item.zh}")
            lines.append(f"STANDARD_EN: {item.standard_en}")
            lines.append(f"USER_EN: {item.user_en}")
            lines.append("---")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[BenativeReviewOutput]:
        results: list[BenativeReviewOutput] = []
        fields = [
            "article_id",
            "sentence_index",
            "accuracy_score",
            "naturalness_score",
            "issue_type",
            "user_en",
            "standard_en",
            "suggested_en",
            "feedback",
        ]
        for item in split_batch_items(raw_output):
            for line in item.splitlines():
                line = line.strip()
                if not line or line == "(none)":
                    continue
                parsed = parse_tab_line(line, len(fields))
                if not parsed:
                    continue
                row = dict(zip(fields, parsed))
                try:
                    row["sentence_index"] = int(row["sentence_index"])
                    row["accuracy_score"] = int(row["accuracy_score"])
                    row["naturalness_score"] = int(row["naturalness_score"])
                except (TypeError, ValueError):
                    continue
                results.append(BenativeReviewOutput(**row))
        return results

    def to_md(self, parsed_data: list[BenativeReviewOutput]) -> str:
        if not parsed_data:
            return "# Be Native Review\n\n(none)\n"

        lines = ["# Be Native Review", ""]
        for item in parsed_data:
            lines.append(f"## {item.article_id}:{item.sentence_index}")
            lines.append(f"- **准确度**: {item.accuracy_score}/100")
            lines.append(f"- **自然度**: {item.naturalness_score}/100")
            lines.append(f"- **问题类型**: {item.issue_type}")
            lines.append(f"- **你的回答**: {item.user_en}")
            lines.append(f"- **标准表达**: {item.standard_en}")
            lines.append(f"- **建议表达**: {item.suggested_en}")
            lines.append(f"- **反馈**: {item.feedback}")
            lines.append("")
        return "\n".join(lines)
