import json
from pathlib import Path

from nanobot.counter.engine import CounterEngine


def _write_trigger(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "triggers": [
                    {
                        "id": "vocab_analysis",
                        "enabled": True,
                        "condition": {
                            "kind": "turn_count",
                            "count": count,
                            "scope": "session",
                        },
                        "target": {"subagent": "vocab"},
                        "cursor": {"offset": 0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_counter_engine_reloads_trigger_count_when_file_changes(tmp_path: Path) -> None:
    trigger_file = tmp_path / "mode" / "freechat" / "trigger" / "triggers.json"
    _write_trigger(trigger_file, 2)

    engine = CounterEngine(tmp_path)
    engine.set_mode("freechat")

    metadata: dict = {}
    assert engine.increment_turn(metadata) == 1
    assert engine.check_triggers(metadata) == []

    _write_trigger(trigger_file, 1)

    assert [trigger.id for trigger in engine.check_triggers(metadata)] == ["vocab_analysis"]
