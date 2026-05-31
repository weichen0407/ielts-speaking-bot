"""Tests for SubagentManager."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.subagent import SubagentManager
from nanobot.agent.subagent import SubagentStatus
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider


@pytest.mark.asyncio
async def test_subagent_uses_tool_loader():
    """Verify subagent registers tools via ToolLoader, not hard-coded imports."""
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=Path("/tmp"),
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
    )
    tools = sm._build_tools()
    assert tools.has("read_file")
    assert tools.has("write_file")
    assert not tools.has("message")
    assert not tools.has("spawn")


@pytest.mark.asyncio
async def test_subagent_build_tools_isolates_file_read_state(tmp_path):
    """Each spawned subagent needs a fresh file-state cache."""
    (tmp_path / "note.txt").write_text("hello\n", encoding="utf-8")
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
    )

    first_read = sm._build_tools().get("read_file")
    second_read = sm._build_tools().get("read_file")

    assert first_read is not second_read
    assert (await first_read.execute(path="note.txt")).startswith("1| hello")
    second_result = await second_read.execute(path="note.txt")
    assert second_result.startswith("1| hello")
    assert "File unchanged" not in second_result


def test_subagent_monitor_runs_write_to_root_monitor_when_workspace_is_persona(tmp_path):
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    provider = MagicMock(spec=LLMProvider)
    provider.get_default_model.return_value = "test"
    sm = SubagentManager(
        provider=provider,
        workspace=persona_dir,
        bus=MessageBus(),
        model="test",
        max_tool_result_chars=16_000,
    )
    status = SubagentStatus(
        task_id="abc12345",
        label="vocab",
        task_description="task",
        started_at=time.monotonic(),
    )
    status.phase = "completed"
    status.result = "done"

    sm._append_monitor_run("abc12345", "vocab", "task", {"channel": "test"}, status)

    path = tmp_path / "monitor" / "subagent_runs.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["task_id"] == "abc12345"
    assert rows[0]["label"] == "vocab"
    assert not (persona_dir / "monitor" / "subagent_runs.jsonl").exists()
