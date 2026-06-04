import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.counter.types import CounterTrigger
from nanobot.providers.base import LLMResponse
from nanobot.agent.subagent import SubagentStatus
from nanobot.session.manager import Session


def _write_thread(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "id": "m1",
        "source": {"mode": "freechat", "session_uuid": "session-1", "message_index": 1},
        "role": "user",
        "content": {"type": "text", "text": "I say good very often."},
        "metadata": {"topic": "movies"},
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")


@pytest.mark.asyncio
async def test_processor_gated_subagent_api_mode_writes_artifact_and_monitor(
    tmp_path: Path,
) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock(
        return_value=LLMResponse(
            content="good\tmemorable\tword_choice\t更具体的评价词",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
    )
    bus = MessageBus()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    source = tmp_path / "persona" / "events" / "thread.jsonl"
    _write_thread(source)
    session = Session(
        key="websocket:chat-1",
        session_uuid="session-1",
        metadata={"mode": "freechat", "session_uuid": "session-1"},
    )
    trigger = CounterTrigger.from_dict(
        {
            "id": "freechat_vocab",
            "enabled": True,
            "condition": {
                "kind": "file_line_count",
                "count": 1,
                "scope": "global",
                "path": "persona/events/thread.jsonl",
            },
            "target": {
                "processor": "vocab",
                "subagent": "vocab",
                "execution_mode": "api",
                "input_path": "persona/events/thread.jsonl",
                "output_path": "persona/processor/freechat/vocab.jsonl",
                "batch_size": 20,
                "model": "deepseek-v4-flash",
            },
            "cursor": {"offset": 0},
        }
    )
    trigger._cursor = {"offset": 0}
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-1",
        content="I say good very often.",
    )

    await loop._execute_processor(session, msg, trigger, str(tmp_path / "persona" / "sessions" / "session-1"))
    await asyncio_sleep_for_status_tasks()

    output_path = tmp_path / "persona" / "processor" / "freechat" / "vocab.jsonl"
    assert output_path.exists()
    assert "memorable" in output_path.read_text(encoding="utf-8")
    assert provider.chat_with_retry.mock_calls[0].kwargs["model"] == "deepseek-v4-flash"

    processor_runs = (tmp_path / "monitor" / "processor_runs.jsonl").read_text(encoding="utf-8")
    subagent_runs = (tmp_path / "monitor" / "subagent_runs.jsonl").read_text(encoding="utf-8")
    assert '"processor": "vocab"' in processor_runs
    assert '"subagent": "vocab"' in subagent_runs
    assert '"execution_mode": "api"' in subagent_runs


@pytest.mark.asyncio
async def test_processor_gated_subagent_agentic_mode_uses_subagent_runtime(
    tmp_path: Path,
) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    bus = MessageBus()
    loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")
    loop.subagents.spawn = AsyncMock(return_value="task-agentic")
    loop.subagents.wait_for_subagent = AsyncMock(
        return_value=SubagentStatus(
            task_id="task-agentic",
            label="vocab",
            task_description="",
            started_at=0,
            phase="done",
            result="good\tmemorable\tword_choice\t更具体的评价词",
            usage={"input_tokens": 12, "output_tokens": 6},
        )
    )
    source = tmp_path / "persona" / "events" / "thread.jsonl"
    _write_thread(source)
    session = Session(
        key="websocket:chat-1",
        session_uuid="session-1",
        metadata={"mode": "freechat", "session_uuid": "session-1"},
    )
    trigger = CounterTrigger.from_dict(
        {
            "id": "freechat_vocab",
            "enabled": True,
            "condition": {
                "kind": "file_line_count",
                "count": 1,
                "scope": "global",
                "path": "persona/events/thread.jsonl",
            },
            "target": {
                "processor": "vocab",
                "subagent": "vocab",
                "execution_mode": "agentic",
                "tools": ["thread_query", "artifact_read"],
                "input_path": "persona/events/thread.jsonl",
                "output_path": "persona/processor/freechat/vocab.jsonl",
                "batch_size": 20,
                "model": "deepseek-v4-flash",
            },
            "cursor": {"offset": 0},
        }
    )
    trigger._cursor = {"offset": 0}
    msg = InboundMessage(
        channel="websocket",
        sender_id="user",
        chat_id="chat-1",
        content="I say good very often.",
    )

    await loop._execute_processor(session, msg, trigger, str(tmp_path / "persona" / "sessions" / "session-1"))

    output_path = tmp_path / "persona" / "processor" / "freechat" / "vocab.jsonl"
    assert output_path.exists()
    assert "memorable" in output_path.read_text(encoding="utf-8")
    spawn_kwargs = loop.subagents.spawn.mock_calls[0].kwargs
    assert spawn_kwargs["label"] == "vocab"
    assert spawn_kwargs["model"] == "deepseek-v4-flash"
    assert spawn_kwargs["allowed_tools"] == ["thread_query", "artifact_read"]
    assert "Allowed tool names" in spawn_kwargs["extra_system_prompt"]
    assert "thread_query" in spawn_kwargs["extra_system_prompt"]
    assert "Do not write files" in spawn_kwargs["task"]

    subagent_runs = (tmp_path / "monitor" / "subagent_runs.jsonl").read_text(encoding="utf-8")
    assert '"subagent": "vocab"' in subagent_runs
    assert '"execution_mode": "agentic"' in subagent_runs
    assert '"tools": ["thread_query", "artifact_read"]' in subagent_runs


async def asyncio_sleep_for_status_tasks() -> None:
    # _on_subagent_status_change uses fire-and-forget bus publish tasks.
    import asyncio

    await asyncio.sleep(0)
