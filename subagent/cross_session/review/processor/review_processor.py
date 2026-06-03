"""ReviewProcessor - extracts review points from Level 2 processed files."""

from pathlib import Path

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line
from .schema import ReviewInput, ReviewOutput
from .store import ReviewStore


class ReviewProcessor(BaseDataProcessor[ReviewInput, ReviewOutput]):
    """Review 处理器 - 从 Level 2 文件提取复习点"""

    name = "review"

    def get_input_schema(self) -> type[ReviewInput]:
        return ReviewInput

    def get_output_schema(self) -> type[ReviewOutput]:
        return ReviewOutput

    def _filter_fields(self, item: dict) -> dict:
        """Adapt Level 2 processor artifacts into ReviewInput."""
        result = super()._filter_fields(item)
        if result.get("content"):
            result.setdefault("role", item.get("role") or "processor")
            return result

        if {"original", "improved", "type", "reason"} <= item.keys():
            result.update({
                "role": "processor",
                "source": "vocab",
                "content": (
                    f"{item.get('original')} -> {item.get('improved')} "
                    f"({item.get('type')}): {item.get('reason')}"
                ),
            })
        elif {"original", "improved", "grammar_type"} <= item.keys():
            explanation = item.get("explanation") or ""
            result.update({
                "role": "processor",
                "source": "polisher",
                "content": (
                    f"{item.get('original')} -> {item.get('improved')} "
                    f"({item.get('grammar_type')}): {explanation}"
                ),
            })
        elif {"title", "content"} <= item.keys():
            details = [
                str(item.get("title") or ""),
                str(item.get("content") or ""),
                str(item.get("category") or ""),
                str(item.get("reference") or ""),
                str(item.get("context") or ""),
            ]
            result.update({
                "role": "processor",
                "source": "notes",
                "content": " | ".join(part for part in details if part),
            })

        if "topic" in item and item.get("topic") is not None:
            result["topic"] = item.get("topic")
        return result

    def get_system_prompt(self) -> str:
        return r"""You are a review point extractor.
Given content from Level 2 processed files (vocab, polisher, notes), extract meaningful knowledge points worth reviewing.

Output format: tab-separated fields, one per line.

Format: review_point	question_type	familiarity_hint	topic

Question types:
- sentence_use: "Please use this expression in a sentence"
- translation: "Translate this into English"
- correction: "Correct this sentence if needed"
- explanation: "Explain this phrase/pattern"

Familiarity hint (1-5, your guess of how familiar user is):
- 1 = likely new/not seen
- 3 = seen but needs practice
- 5 = very familiar

Topics: sports, food, hobbies, family, travel, work, education, technology, environment, culture, etc.

Example:
be quite fond of	sentence_use	2	hobbies
three-point shot	sentence_use	3	sports
excellent	correction	4	null

If no content to process, output (none)."""

    def build_user_prompt(self, data: list[ReviewInput]) -> str:
        lines = []
        for item in data:
            source = f"[{item.source}]" if item.source else ""
            topic = f"({item.topic})" if item.topic else ""
            lines.append(f"{source} {item.content} {topic}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[ReviewOutput]:
        """解析 LLM 输出（第二工程层）"""
        results = []
        field_count = 4  # review_point, question_type, familiarity_hint, topic

        for line in raw_output.strip().split("\n"):
            line = line.strip()
            if not line or line == "(none)":
                continue

            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    familiarity = int(parts[2]) if parts[2].isdigit() else 3
                except (ValueError, IndexError):
                    familiarity = 3

                results.append(ReviewOutput(
                    review_point=parts[0],
                    question_type=parts[1] if len(parts) > 1 else "sentence_use",
                    familiarity_hint=familiarity,
                    topic=parts[3] if len(parts) > 3 else None,
                ))
        return results

    def to_md(self, parsed_data: list[ReviewOutput]) -> str:
        """生成 Review MD 格式"""
        if not parsed_data:
            return "# Review\n\n(none)\n"

        lines = ["# Review", ""]
        for i, item in enumerate(parsed_data, 1):
            lines.append(f"## {i}. {item.review_point}")
            lines.append(f"- **题目类型**: {item.question_type}")
            lines.append(f"- **熟悉度**: {item.familiarity_hint}/5")
            if item.topic:
                lines.append(f"- **话题**: {item.topic}")
            lines.append("")
        return "\n".join(lines)

    def process_all(
        self,
        input_paths: list[Path],
        output_path: Path,
        batch_size: int = 50,
        format: str = "both",
    ):
        """
        处理所有 Level 2 文件，提取复习点

        Args:
            input_paths: Level 2 文件路径列表
            output_path: review_points.jsonl 输出路径
            batch_size: 每批处理条数
            format: 输出格式
        """
        from .store import ReviewStore, ReviewPoint

        # Collect all data from input files
        all_data = []
        for input_path in input_paths:
            if input_path.exists():
                file_data = self.read(input_path)
                all_data.extend(file_data)

        if not all_data:
            return

        # Preprocess
        processed = self.preprocess(all_data)
        if not processed:
            return

        # Build prompt and call LLM
        user_prompt = self.build_user_prompt(processed)
        system_prompt = self.get_system_prompt()

        raw_output = self._call_llm(system_prompt, user_prompt)
        if not raw_output:
            return

        # Parse output
        parsed = self.parse_llm_output(raw_output)
        if not parsed:
            return

        # Update ReviewStore
        review_store = ReviewStore(output_path.parent)
        self._update_store(review_store, parsed)

        # Serialize
        self.serialize(parsed, output_path, format)

    async def aprocess_all(
        self,
        input_paths: list[Path],
        output_path: Path,
        batch_size: int = 50,
        format: str = "both",
    ):
        """
        Async runtime version for AgentLoop.

        ReviewProcessor consumes multiple Level 2 files, so it cannot rely on
        BaseDataProcessor.aprocess_all(input_path=...).
        """
        from .store import ReviewStore

        all_data = []
        for input_path in input_paths:
            if input_path.exists():
                file_data = self.read(input_path)
                all_data.extend(file_data)

        if not all_data:
            return

        processed = self.preprocess(all_data)
        if not processed:
            return

        user_prompt = self.build_user_prompt(processed)
        system_prompt = self.get_system_prompt()

        raw_output = await self._acall_llm(system_prompt, user_prompt)
        if not raw_output:
            return

        parsed = self.parse_llm_output(raw_output)
        if not parsed:
            return

        review_store = ReviewStore(output_path.parent)
        self._update_store(review_store, parsed)
        self.serialize(parsed, output_path, format)

    def _update_store(self, store: ReviewStore, outputs: list[ReviewOutput]) -> None:
        """将解析结果更新到 ReviewStore"""
        from .store import ReviewPoint

        for output in outputs:
            point, created = store.get_or_create_point(
                content=output.review_point,
                point_type=output.question_type,
                topic=output.topic or "general",
                source="review_processor",
            )
            if created:
                # Update index with familiarity hint
                if point.id in store.index:
                    store.index[point.id].familiarity = output.familiarity_hint
