import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.subagent_context import ArtifactReadTool, ThreadQueryTool, UserProfileTool
from nanobot.bus.queue import MessageBus


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_subagent_context_tools_register_and_allowlist(tmp_path: Path) -> None:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    mgr = SubagentManager(
        provider=provider,
        workspace=tmp_path,
        bus=MessageBus(),
        max_tool_result_chars=4096,
    )

    tools = mgr._build_tools(
        allowed_tools=["thread_query", "artifact_read", "user_profile", "wiki_query"]
    )

    assert tools.tool_names == ["thread_query", "artifact_read", "user_profile", "wiki_query"]
    assert tools.get("thread_query").read_only is True
    assert tools.get("artifact_read").read_only is True
    assert tools.get("user_profile").read_only is True
    assert tools.get("wiki_query").read_only is True


@pytest.mark.asyncio
async def test_thread_query_reads_recent_filtered_messages(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "persona" / "events" / "thread.jsonl",
        [
            {
                "id": "s1:0",
                "timestamp": "2026-06-04T10:00:00",
                "role": "user",
                "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 0},
                "content": {"type": "text", "text": "I like basketball."},
            },
            {
                "id": "s1:1",
                "timestamp": "2026-06-04T10:00:01",
                "role": "assistant",
                "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 1},
                "content": {"type": "text", "text": "Nice."},
            },
        ],
    )

    result = await ThreadQueryTool(tmp_path).execute(query="basketball", role="user", limit=5)

    assert result["status"] == "ok"
    assert result["count"] == 1
    assert result["messages"][0]["text"] == "I like basketball."


@pytest.mark.asyncio
async def test_artifact_read_reads_allowed_artifact_and_blocks_other_paths(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "persona" / "processor" / "freechat" / "vocab.jsonl",
        [{"original": "good", "improved": "memorable"}],
    )
    (tmp_path / "secrets.txt").write_text("nope", encoding="utf-8")

    tool = ArtifactReadTool(tmp_path)
    ok = await tool.execute(artifact="vocab", limit=10)
    blocked = await tool.execute(path="secrets.txt", limit=10)

    assert ok["status"] == "ok"
    assert ok["rows"][0]["improved"] == "memorable"
    assert blocked["status"] == "error"


@pytest.mark.asyncio
async def test_user_profile_reads_memory_files(tmp_path: Path) -> None:
    (tmp_path / "persona" / "memory").mkdir(parents=True)
    (tmp_path / "persona" / "USER.md").write_text("User likes football.", encoding="utf-8")
    (tmp_path / "persona" / "memory" / "MEMORY.md").write_text("Favorite team: Arsenal.", encoding="utf-8")

    result = await UserProfileTool(tmp_path).execute()

    assert result["status"] == "ok"
    assert "football" in result["files"]["user"]
    assert "Arsenal" in result["files"]["memory"]
