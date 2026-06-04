import json
from pathlib import Path

import pytest

from nanobot.providers.base import LLMResponse
from subagent.single_session.polisher.processor.processor import PolisherProcessor
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


def test_processor_middleware_input_and_output_defaults(tmp_path: Path) -> None:
    input_path = tmp_path / "thread.jsonl"
    _write_thread(input_path)

    processor = VocabProcessor()
    processed = processor.preprocess(processor.read(input_path))
    subagent_input = processor.prepare_subagent_input(
        processed,
        mode="freechat",
        execution_mode="agentic",
        tools=["thread_query", "artifact_read"],
        context={"trigger_id": "freechat_vocab", "ignored": {"nested": True}},
    )
    parsed = processor.parse_subagent_output(
        "very much\ta lot\tcollocation\t日常口语里更自然"
    )

    assert "processor: vocab" in subagent_input
    assert "mode: freechat" in subagent_input
    assert "execution_mode: agentic" in subagent_input
    assert "tools: thread_query, artifact_read" in subagent_input
    assert '"trigger_id": "freechat_vocab"' in subagent_input
    assert "用户说: I like basketball very much." in subagent_input
    assert len(parsed) == 1
    assert parsed[0].improved == "a lot"


def test_vocab_and_polisher_accept_benative_response_events() -> None:
    row = {
        "session_uuid": "session-1",
        "article_id": "paris_football_trip_001",
        "sentence_index": 0,
        "zh": "巴黎以博物馆和咖啡馆闻名。",
        "standard_en": "Paris is famous for museums and cafes.",
        "user_en": "paris is a famous for museum and cafe.",
    }

    vocab_processed = VocabProcessor().preprocess([row])
    polisher_processed = PolisherProcessor().preprocess([row])

    assert len(vocab_processed) == 1
    assert vocab_processed[0].role == "user"
    assert vocab_processed[0].content == "paris is a famous for museum and cafe."
    assert vocab_processed[0].topic == "paris_football_trip_001"
    assert vocab_processed[0].mode == "benative"
    assert len(polisher_processed) == 1
    assert polisher_processed[0].role == "user"
    assert polisher_processed[0].content == "paris is a famous for museum and cafe."


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
