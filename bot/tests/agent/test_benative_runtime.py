import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


def _make_loop(tmp_path: Path) -> AgentLoop:
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.chat_with_retry = AsyncMock()
    return AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )


def _write_pairs(tmp_path: Path) -> None:
    pairs_dir = tmp_path / "persona" / "benative" / "pairs"
    pairs_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {"sentence_index": 0, "zh": "我喜欢在周末打篮球。", "en": "I enjoy playing basketball on weekends."},
        {"sentence_index": 1, "zh": "我想去巴黎看一场足球比赛。", "en": "I want to watch a football match in Paris."},
    ]
    (pairs_dir / "article-1.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_benative_answer_advances_sentence_without_llm(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    _write_pairs(tmp_path)

    session = loop.sessions.get_or_create("websocket:s1")
    session.metadata["mode"] = "benative"
    session.metadata["benative_article_id"] = "article-1"
    loop.sessions.save(session)

    progress_file = loop.sessions._get_session_dir(session.key) / "notes" / "benative_progress.json"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(
        json.dumps(
            {"article_id": "article-1", "current_sentence": 0, "total_sentences": 2},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = await loop._process_message(
        InboundMessage(
            channel="websocket",
            sender_id="user",
            chat_id="s1",
            content="I like playing basketball on weekends.",
        )
    )

    assert result is not None
    assert "Sentence 2/2" in result.content
    assert "我想去巴黎看一场足球比赛。" in result.content
    loop.provider.chat_with_retry.assert_not_awaited()

    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    assert progress["current_sentence"] == 1

    global_log = tmp_path / "persona" / "benative" / "events" / "responses.jsonl"
    global_rows = [json.loads(line) for line in global_log.read_text(encoding="utf-8").splitlines()]
    assert global_rows[0]["article_id"] == "article-1"
    assert global_rows[0]["sentence_index"] == 0
    assert global_rows[0]["standard_en"] == "I enjoy playing basketball on weekends."
    assert global_rows[0]["user_en"] == "I like playing basketball on weekends."

    session_log = tmp_path / "persona" / "benative" / "sessions" / "s1" / "responses.jsonl"
    session_rows = [json.loads(line) for line in session_log.read_text(encoding="utf-8").splitlines()]
    assert session_rows[0]["mode"] == "benative"
    assert session_rows[0]["sentence_index"] == 0


@pytest.mark.asyncio
async def test_benative_answer_completes_article_without_llm(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    _write_pairs(tmp_path)

    session = loop.sessions.get_or_create("websocket:s1")
    session.metadata["mode"] = "benative"
    session.metadata["benative_article_id"] = "article-1"
    loop.sessions.save(session)

    progress_file = loop.sessions._get_session_dir(session.key) / "notes" / "benative_progress.json"
    progress_file.parent.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(
        json.dumps(
            {"article_id": "article-1", "current_sentence": 1, "total_sentences": 2},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = await loop._process_message(
        InboundMessage(
            channel="websocket",
            sender_id="user",
            chat_id="s1",
            content="I want to watch a football match in Paris.",
        )
    )

    assert result is not None
    assert "This article is complete" in result.content
    loop.provider.chat_with_retry.assert_not_awaited()

    progress = json.loads(progress_file.read_text(encoding="utf-8"))
    assert progress["current_sentence"] == 2


def test_benative_mode_does_not_schedule_wiki_sync(tmp_path: Path, monkeypatch) -> None:
    loop = _make_loop(tmp_path)
    monkeypatch.delenv("NANOBOT_WIKI_SYNC_MODES", raising=False)
    monkeypatch.setenv("NANOBOT_WIKI_SYNC_INTERVAL", "1")

    assert loop._should_sync_wiki(1, "freechat") is True
    assert loop._should_sync_wiki(1, "benative") is False
