import json
from pathlib import Path

import pytest

from nanobot.providers.base import LLMResponse
from subagent.cross_session.progress_organizer.processor.processor import ProgressOrganizerProcessor
from subagent.cross_session.review.processor.review_processor import ReviewProcessor
from subagent.single_session.quiz.processor.processor import QuizProcessor


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    async def chat_with_retry(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(content=self.content)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_review_processor_consumes_vocab_artifact(tmp_path: Path) -> None:
    vocab_path = tmp_path / "vocab.jsonl"
    output_path = tmp_path / "review" / "review_points.jsonl"
    _write_jsonl(
        vocab_path,
        [
            {
                "original": "I like basketball very much.",
                "improved": "I'm really into basketball.",
                "type": "expression",
                "reason": "更自然的兴趣表达",
                "topic": "sports",
            }
        ],
    )
    provider = FakeProvider(
        "I'm really into basketball\tsentence_use\t2\tsports"
    )
    processor = ReviewProcessor()
    processor.configure_llm(provider=provider, model="deepseek-v4-flash")

    processor.process_all(input_paths=[vocab_path], output_path=output_path)

    assert provider.calls
    user_prompt = provider.calls[0]["messages"][1]["content"]
    assert "[vocab]" in user_prompt
    assert "I'm really into basketball" in user_prompt
    assert output_path.exists()
    assert "sentence_use" in output_path.read_text(encoding="utf-8")


def test_quiz_processor_consumes_review_artifact(tmp_path: Path) -> None:
    review_path = tmp_path / "review_points.jsonl"
    output_path = tmp_path / "quiz.jsonl"
    _write_jsonl(
        review_path,
        [
            {
                "review_point": "I'm really into basketball",
                "question_type": "sentence_use",
                "familiarity_hint": 2,
                "topic": "sports",
            }
        ],
    )
    provider = FakeProvider(
        'Please use "I\'m really into basketball" in a sentence.\tI\'m really into basketball because it helps me relax.\tintermediate\tsports'
    )
    processor = QuizProcessor()
    processor.configure_llm(provider=provider, model="deepseek-v4-flash")

    processor.process_all(input_path=review_path, output_path=output_path)

    assert provider.calls
    assert output_path.exists()
    assert "intermediate" in output_path.read_text(encoding="utf-8")
    assert "basketball" in output_path.with_suffix(".md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_progress_organizer_consumes_progress_tracker_artifact(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress_bank.jsonl"
    output_path = tmp_path / "organized_progress.jsonl"
    _write_jsonl(
        progress_path,
        [
            {
                "category": "preference",
                "intent": "positive",
                "expression": "I'm really into basketball",
                "content": "I like basketball very much.",
            }
        ],
    )
    provider = FakeProvider(
        "habit\tpositive\tbe really into basketball"
    )
    processor = ProgressOrganizerProcessor()
    processor.configure_llm(provider=provider, model="deepseek-v4-flash")

    await processor.aprocess_all(input_path=progress_path, output_path=output_path)

    assert provider.calls
    user_prompt = provider.calls[0]["messages"][1]["content"]
    assert "I'm really into basketball" in user_prompt
    assert output_path.exists()
    assert "be really into basketball" in output_path.read_text(encoding="utf-8")
