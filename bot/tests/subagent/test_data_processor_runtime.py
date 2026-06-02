import json
from pathlib import Path

import pytest

from nanobot.providers.base import LLMResponse
from subagent.single_session.vocab.processor.processor import VocabProcessor


class FakeProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    async def chat_with_retry(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(content=self.content)


def _write_thread(path: Path) -> None:
    events = [
        {
            "id": "m1",
            "timestamp": "2026-06-02T14:00:00+08:00",
            "source": {
                "mode": "freechat",
                "session_uuid": "session-1",
                "message_index": 1,
            },
            "role": "user",
            "content": {"type": "text", "text": "I like basketball very much."},
            "metadata": {"topic": "sports"},
        },
        {
            "id": "m2",
            "timestamp": "2026-06-02T14:01:00+08:00",
            "source": {
                "mode": "freechat",
                "session_uuid": "session-1",
                "message_index": 2,
            },
            "role": "assistant",
            "content": {"type": "text", "text": "That sounds fun."},
            "metadata": {"topic": "sports"},
        },
    ]
    path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def test_preprocess_keeps_role_and_core_source_fields(tmp_path: Path) -> None:
    input_path = tmp_path / "thread.jsonl"
    _write_thread(input_path)

    processor = VocabProcessor()
    processed = processor.preprocess(processor.read(input_path))

    assert len(processed) == 2
    assert processed[0].role == "user"
    assert processed[0].content == "I like basketball very much."
    assert processed[0].topic == "sports"
    assert processed[0].mode == "freechat"


def test_vocab_processor_sync_process_all_writes_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "thread.jsonl"
    output_path = tmp_path / "vocab.jsonl"
    _write_thread(input_path)

    provider = FakeProvider(
        "I like basketball very much.\tI'm really into basketball.\texpression\t更自然的兴趣表达"
    )
    processor = VocabProcessor()
    processor.configure_llm(provider=provider, model="deepseek-v4-flash")

    processor.process_all(input_path=input_path, output_path=output_path, batch_size=10)

    assert provider.calls
    assert provider.calls[0]["model"] == "deepseek-v4-flash"
    assert output_path.exists()
    assert "I'm really into basketball." in output_path.read_text(encoding="utf-8")
    assert "I'm really into basketball." in output_path.with_suffix(".md").read_text(
        encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_vocab_processor_async_process_all_writes_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "thread.jsonl"
    output_path = tmp_path / "vocab.jsonl"
    _write_thread(input_path)

    provider = FakeProvider(
        "very much\ta lot\tcollocation\t日常口语里更自然"
    )
    processor = VocabProcessor()
    processor.configure_llm(provider=provider, model="deepseek-v4-flash")

    await processor.aprocess_all(input_path=input_path, output_path=output_path, batch_size=10)

    assert provider.calls
    assert output_path.exists()
    assert "very much" in output_path.read_text(encoding="utf-8")
