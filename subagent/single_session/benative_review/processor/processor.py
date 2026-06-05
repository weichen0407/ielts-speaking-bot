"""BenativeReviewProcessor - evaluates reconstruction answers."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

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
session_uuid	article_id	sentence_index	accuracy_score	naturalness_score	issue_type	user_en	standard_en	suggested_en	feedback

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
            lines.append(f"SESSION_UUID: {item.session_uuid}")
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
            "session_uuid",
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
                    legacy_fields = fields[1:]
                    legacy_parsed = parse_tab_line(line, len(legacy_fields))
                    if not legacy_parsed:
                        continue
                    parsed = ["unknown", *legacy_parsed]
                if len(parsed) != len(fields):
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

    def attach_input_context(
        self,
        parsed_data: list[BenativeReviewOutput],
        processed_data: list[BenativeReviewInput],
    ) -> list[BenativeReviewOutput]:
        """Fill session_uuid when a model returned the legacy row format."""
        if not parsed_data:
            return parsed_data
        session_by_sentence = {
            (item.article_id, item.sentence_index): item.session_uuid
            for item in processed_data
        }
        enriched: list[BenativeReviewOutput] = []
        for item in parsed_data:
            if item.session_uuid and item.session_uuid != "unknown":
                enriched.append(item)
                continue
            session_uuid = session_by_sentence.get((item.article_id, item.sentence_index))
            if not session_uuid:
                enriched.append(item)
                continue
            data = item.model_dump()
            data["session_uuid"] = session_uuid
            enriched.append(BenativeReviewOutput(**data))
        return enriched

    def fallback_outputs(self, processed_data: list[BenativeReviewInput]) -> list[BenativeReviewOutput]:
        """Guarantee one persisted review row per Be Native answer.

        This fallback is used only when the review subagent returns empty or
        non-parseable output. It keeps the session notes complete while making
        the limitation explicit in the feedback.
        """
        rows: list[BenativeReviewOutput] = []
        for item in processed_data:
            exact = item.user_en.strip().casefold() == item.standard_en.strip().casefold()
            rows.append(
                BenativeReviewOutput(
                    session_uuid=item.session_uuid,
                    article_id=item.article_id,
                    sentence_index=item.sentence_index,
                    accuracy_score=95 if exact else 60,
                    naturalness_score=90 if exact else 55,
                    issue_type="excellent" if exact else "other",
                    user_en=item.user_en,
                    standard_en=item.standard_en,
                    suggested_en=item.standard_en,
                    feedback=(
                        "表达已经非常接近标准句，可以注意大小写和标点。"
                        if exact
                        else "本轮 AI review 没有返回可解析结果，先保留标准表达作为参考；可以对比语序、用词和遗漏信息。"
                    ),
                )
            )
        return rows

    def serialize(
        self,
        data: list[BenativeReviewOutput],
        output_path: Path,
        format: str = "both",
    ):
        """Write the global review artifact and a session-local review artifact."""
        super().serialize(data, output_path, format)
        if not data:
            return

        workspace = _workspace_from_output(output_path)
        grouped: dict[str, list[BenativeReviewOutput]] = defaultdict(list)
        for item in data:
            if item.session_uuid and item.session_uuid != "unknown":
                grouped[item.session_uuid].append(item)

        for session_uuid, items in grouped.items():
            notes_dir = workspace / "persona" / "benative" / "sessions" / session_uuid / "notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            session_jsonl = notes_dir / "review.jsonl"
            if format in ("jsonl", "both"):
                with session_jsonl.open("a", encoding="utf-8") as fh:
                    for item in items:
                        fh.write(item.model_dump_json() + "\n")
            if format in ("md", "both"):
                session_items = _read_review_items(session_jsonl) if session_jsonl.exists() else items
                (notes_dir / "review.md").write_text(self.to_md(session_items), encoding="utf-8")


def _workspace_from_output(output_path: Path) -> Path:
    for parent in [output_path, *output_path.parents]:
        if parent.name == "persona":
            return parent.parent
    return output_path.parent


def _read_review_items(path: Path) -> list[BenativeReviewOutput]:
    items: list[BenativeReviewOutput] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                items.append(BenativeReviewOutput.model_validate(json.loads(line)))
            except Exception:
                continue
    return items
