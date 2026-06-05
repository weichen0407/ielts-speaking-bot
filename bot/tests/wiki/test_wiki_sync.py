import json
from pathlib import Path
import pytest

from nanobot.agent.wiki_sync import sync_session_to_wiki


class FakeProvider:
    def __init__(self) -> None:
        self.called = False

    async def chat(self, *, messages, **_kwargs):
        self.called = True
        raise AssertionError("wiki sync core should not call provider.chat")


@pytest.mark.asyncio
async def test_wiki_sync_reads_global_thread_context(tmp_path: Path) -> None:
    session_uuid = "session-1"
    data_dir = tmp_path / "persona" / "events"
    data_dir.mkdir(parents=True)
    events = [
        {
            "source": {"mode": "freechat", "session_uuid": session_uuid, "message_index": 0},
            "role": "user",
            "content": {"type": "text", "text": "I enjoy local food."},
        },
        {
            "source": {"mode": "freechat", "session_uuid": session_uuid, "message_index": 1},
            "role": "assistant",
            "content": {"type": "text", "text": "That sounds meaningful."},
        },
    ]
    (data_dir / "thread.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    provider = FakeProvider()
    result = await sync_session_to_wiki(
        session_key=session_uuid,
        session_dir=str(tmp_path / "persona" / "sessions" / session_uuid),
        workspace=tmp_path,
        provider=provider,
        model="test-model",
    )

    assert result["status"] == "ok"
    assert result["messages"] == 2
    assert result["candidates"] >= 1
    assert result["applied"] >= 1
    assert provider.called is False
    assert (tmp_path / "persona" / "wiki" / "state" / "sync_log.jsonl").exists()


@pytest.mark.asyncio
async def test_wiki_sync_skips_benative_thread_context(tmp_path: Path) -> None:
    session_uuid = "benative-session"
    events_dir = tmp_path / "persona" / "events"
    events_dir.mkdir(parents=True)
    events = [
        {
            "source": {"mode": "benative", "session_uuid": session_uuid, "message_index": 0},
            "role": "user",
            "content": {"type": "text", "text": "paris is a famous for museum and cafe"},
        },
        {
            "source": {"mode": "benative", "session_uuid": session_uuid, "message_index": 1},
            "role": "assistant",
            "content": {"type": "text", "text": "Recorded sentence 1/4."},
        },
    ]
    (events_dir / "thread.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    result = await sync_session_to_wiki(
        session_key=session_uuid,
        session_dir=str(tmp_path / "persona" / "sessions" / session_uuid),
        workspace=tmp_path,
        provider=FakeProvider(),
        model="test-model",
    )

    assert result["status"] == "ok"
    assert result["messages"] == 0
    assert result["candidates"] == 0
    assert result["applied"] == 0
