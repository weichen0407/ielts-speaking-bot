import json
import time
from pathlib import Path
from types import SimpleNamespace

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket import WebSocketChannel


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

    channel = WebSocketChannel({"enabled": True}, MessageBus())
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
