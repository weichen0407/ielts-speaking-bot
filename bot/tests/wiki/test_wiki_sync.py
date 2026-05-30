import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.wiki_sync import sync_session_to_wiki


class FakeProvider:
    def __init__(self) -> None:
        self.messages = None

    async def chat(self, *, messages, **_kwargs):
        self.messages = messages
        return SimpleNamespace(content="(none)")


@pytest.mark.asyncio
async def test_wiki_sync_reads_global_thread_context(tmp_path: Path) -> None:
    session_uuid = "session-1"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    events = [
        {
            "source": {"session_uuid": session_uuid, "message_index": 0},
            "role": "user",
            "content": {"type": "text", "text": "I enjoy local food."},
        },
        {
            "source": {"session_uuid": session_uuid, "message_index": 1},
            "role": "assistant",
            "content": {"type": "text", "text": "That sounds meaningful."},
        },
    ]
    (data_dir / "thread.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    provider = FakeProvider()
    patches = await sync_session_to_wiki(
        session_key=session_uuid,
        session_dir=str(tmp_path / "persona" / "sessions" / session_uuid),
        workspace=tmp_path,
        provider=provider,
        model="test-model",
    )

    assert patches == 0
    assert provider.messages is not None
    prompt = provider.messages[1]["content"]
    assert "User: I enjoy local food." in prompt
    assert "Assistant: That sounds meaningful." in prompt
