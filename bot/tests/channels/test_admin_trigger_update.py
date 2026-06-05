import json
import time
from pathlib import Path
from types import SimpleNamespace

from nanobot.channels.websocket import WebSocketChannel
from nanobot.session.manager import SessionManager


def test_admin_trigger_update_writes_count(tmp_path: Path, monkeypatch) -> None:
    trigger_file = tmp_path / "mode" / "freechat" / "trigger" / "triggers.json"
    trigger_file.parent.mkdir(parents=True)
    trigger_file.write_text(
        json.dumps(
            {
                "version": 1,
                "triggers": [
                    {
                        "id": "vocab_analysis",
                        "enabled": True,
                        "condition": {"kind": "turn_count", "count": 3, "scope": "session"},
                        "target": {"subagent": "vocab"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    channel = WebSocketChannel({"enabled": True}, SimpleNamespace())
    channel._api_tokens["tok"] = time.monotonic() + 60
    monkeypatch.setattr(channel, "_project_root", lambda: tmp_path)
    request = SimpleNamespace(
        path=(
            "/api/admin/triggers"
            "?source=mode/freechat/trigger/triggers.json"
            "&id=vocab_analysis"
            "&count=1"
        ),
        headers={"Authorization": "Bearer tok"},
        body=b"",
    )

    response = channel._handle_admin_trigger_update(request)

    assert response.status_code == 200
    data = json.loads(trigger_file.read_text(encoding="utf-8"))
    assert data["triggers"][0]["condition"]["count"] == 1


def test_admin_monitor_includes_trigger_decisions(tmp_path: Path, monkeypatch) -> None:
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir()
    (monitor_dir / "trigger_decisions.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-05-31T00:00:00Z",
                "trigger_id": "vocab_analysis",
                "decision": "skipped",
                "reason": "turn_count_not_due",
                "mode": "freechat",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    channel = WebSocketChannel({"enabled": True}, SimpleNamespace())
    channel._api_tokens["tok"] = time.monotonic() + 60
    monkeypatch.setattr(channel, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(channel, "_monitor_triggers", lambda root: ([], []))
    monkeypatch.setattr(channel, "_monitor_context_prompt_files", lambda root: [])
    monkeypatch.setattr(channel, "_monitor_recent_activity", lambda root: [])
    request = SimpleNamespace(
        path="/api/admin/monitor",
        headers={"Authorization": "Bearer tok"},
        body=b"",
    )

    response = channel._handle_admin_monitor(request)

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["trigger_decisions"][0]["trigger_id"] == "vocab_analysis"
    assert payload["trigger_decisions"][0]["reason"] == "turn_count_not_due"


def test_admin_monitor_includes_benative_processor_and_subagent_runs(tmp_path: Path, monkeypatch) -> None:
    monitor_dir = tmp_path / "monitor"
    monitor_dir.mkdir()
    (monitor_dir / "processor_runs.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-06-04T10:00:00Z",
                "trigger_id": "benative_review",
                "processor": "benative_review",
                "subagent": "benative_review",
                "execution_mode": "api",
                "tools": [],
                "mode": "benative",
                "status": "completed",
                "model": "deepseek-v4-flash",
                "input_rows": 1,
                "output_rows": 1,
                "output_preview": [
                    {
                        "article_id": "article_001",
                        "sentence_index": 2,
                        "issue_type": "grammar",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (monitor_dir / "subagent_runs.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-06-04T10:00:01Z",
                "task_id": "task-1",
                "label": "benative_review",
                "subagent": "benative_review",
                "phase": "done",
                "model": "deepseek-v4-flash",
                "stop_reason": "completed",
                "origin": {
                    "kind": "processor_middleware",
                    "trigger_id": "benative_review",
                    "processor": "benative_review",
                    "mode": "benative",
                },
                "result": "ARTICLE article_001 review complete",
                "execution_mode": "api",
                "tools": [],
                "input_rows": 1,
                "output_rows": 1,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    channel = WebSocketChannel({"enabled": True}, SimpleNamespace())
    channel._api_tokens["tok"] = time.monotonic() + 60
    monkeypatch.setattr(channel, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(channel, "_monitor_triggers", lambda root: ([], []))
    monkeypatch.setattr(channel, "_monitor_context_prompt_files", lambda root: [])
    monkeypatch.setattr(channel, "_monitor_recent_activity", lambda root: [])
    request = SimpleNamespace(
        path="/api/admin/monitor",
        headers={"Authorization": "Bearer tok"},
        body=b"",
    )

    response = channel._handle_admin_monitor(request)

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["processor_runs"][0]["mode"] == "benative"
    assert payload["processor_runs"][0]["output_preview"][0]["article_id"] == "article_001"
    assert payload["processor_runs"][0]["output_preview"][0]["sentence_index"] == 2
    assert payload["subagent_runs"][0]["origin"]["kind"] == "processor_middleware"
    assert payload["subagent_runs"][0]["origin"]["mode"] == "benative"


def test_benative_session_notes_read_session_local_review(tmp_path: Path, monkeypatch) -> None:
    manager = SessionManager(workspace=tmp_path / "persona")
    session = manager.get_or_create("websocket:session-001")
    session.metadata["mode"] = "benative"
    manager.save(session)

    notes_dir = tmp_path / "persona" / "benative" / "sessions" / "session-001" / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "review.md").write_text("# Session Review\n\nonly this session", encoding="utf-8")

    global_dir = tmp_path / "persona" / "processor" / "benative"
    global_dir.mkdir(parents=True)
    (global_dir / "review.md").write_text("# Global Review\n\nwrong session", encoding="utf-8")

    channel = WebSocketChannel({"enabled": True}, SimpleNamespace())
    channel._api_tokens["tok"] = time.monotonic() + 60
    channel._session_manager = manager
    monkeypatch.setattr(channel, "_project_root", lambda: tmp_path)
    request = SimpleNamespace(
        path="/api/sessions/websocket%3Asession-001/notes",
        headers={"Authorization": "Bearer tok"},
        body=b"",
    )

    response = channel._handle_session_notes(request, "websocket%3Asession-001")

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["mode"] == "benative"
    assert payload["review"] == "# Session Review\n\nonly this session"
    assert payload["vocab"] == ""
    assert payload["polisher"] == ""
