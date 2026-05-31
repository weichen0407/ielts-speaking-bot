import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_benative
from nanobot.command.router import CommandContext
from nanobot.session.manager import Session


class _FakeSessions:
    def __init__(self, root: Path, session: Session) -> None:
        self.sessions_dir = root / "persona" / "sessions"
        self.sessions_dir.mkdir(parents=True)
        self._session = session

    def get_or_create(self, _key: str) -> Session:
        return self._session

    def save(self, _session: Session) -> None:
        return None

    def _get_session_dir(self, _key: str) -> Path:
        path = self.sessions_dir / self._session.session_uuid
        path.mkdir(parents=True, exist_ok=True)
        return path


def _context(tmp_path: Path, session: Session, args: str) -> CommandContext:
    loop = SimpleNamespace(
        workspace=tmp_path,
        sessions=_FakeSessions(tmp_path, session),
        counter_engine=SimpleNamespace(set_mode=lambda _mode: None),
    )
    msg = InboundMessage(
        channel="websocket",
        sender_id="u1",
        chat_id="c1",
        content="/benative",
    )
    return CommandContext(
        msg=msg,
        session=session,
        key=session.key,
        raw="/benative",
        args=args,
        loop=loop,
    )


@pytest.mark.asyncio
async def test_benative_lists_articles_from_persona_benative(tmp_path: Path) -> None:
    session = Session(key="websocket:c1", session_uuid="s1")
    articles_dir = tmp_path / "persona" / "benative" / "articles"
    pairs_dir = tmp_path / "persona" / "benative" / "pairs"
    articles_dir.mkdir(parents=True)
    pairs_dir.mkdir(parents=True)
    (articles_dir / "a1.json").write_text(
        json.dumps({"id": "a1", "title": "Daily News", "source": "Reuters", "topic": "society"}),
        encoding="utf-8",
    )
    (pairs_dir / "a1.jsonl").write_text('{"en":"Hello","zh":"你好","sentence_index":0}\n', encoding="utf-8")

    response = await cmd_benative(_context(tmp_path, session, ""))

    assert response is not None
    assert "Daily News" in response.content
    assert "1 sentences" in response.content
    assert session.metadata["mode"] == "benative"


@pytest.mark.asyncio
async def test_benative_select_counts_pairs_from_persona_benative(tmp_path: Path) -> None:
    session = Session(key="websocket:c1", session_uuid="s1")
    pairs_dir = tmp_path / "persona" / "benative" / "pairs"
    pairs_dir.mkdir(parents=True)
    (pairs_dir / "a1.jsonl").write_text(
        '{"en":"One","zh":"一","sentence_index":0}\n{"en":"Two","zh":"二","sentence_index":1}\n',
        encoding="utf-8",
    )

    response = await cmd_benative(_context(tmp_path, session, "select a1"))

    assert response is not None
    assert "0/2 sentences" in response.content
    progress = json.loads(
        (tmp_path / "persona" / "sessions" / "s1" / "notes" / "benative_progress.json").read_text(
            encoding="utf-8"
        )
    )
    assert progress["article_id"] == "a1"
    assert progress["total_sentences"] == 2
