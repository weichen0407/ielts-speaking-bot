import json
from pathlib import Path

from nanobot.counter.engine import CounterEngine


def test_counter_engine_ensure_mode_loads_session_triggers(tmp_path: Path) -> None:
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
                        "condition": {
                            "kind": "turn_count",
                            "count": 1,
                            "scope": "session",
                        },
                        "target": {"subagent": "vocab"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    engine = CounterEngine(tmp_path)
    metadata = {"mode": "freechat"}

    engine.ensure_mode(metadata["mode"])
    engine.increment_turn(metadata)

    assert [trigger.id for trigger in engine.check_triggers(metadata)] == ["vocab_analysis"]
    decisions = [
        json.loads(line)
        for line in (tmp_path / "monitor" / "trigger_decisions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[-1]["decision"] == "eligible"
    assert decisions[-1]["reason"] == "turn_count_threshold_met"


def test_counter_engine_resolves_project_root_when_workspace_is_persona(tmp_path: Path) -> None:
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
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
                        "condition": {
                            "kind": "turn_count",
                            "count": 1,
                            "scope": "session",
                        },
                        "target": {
                            "subagent": "vocab",
                            "prompt_file": "subagent/single_session/vocab/context/vocab_subagent.md",
                            "task_template": "Workspace: {workspace}\nSession: {session_dir}",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    prompt_file = tmp_path / "subagent" / "single_session" / "vocab" / "context" / "vocab_subagent.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("prompt", encoding="utf-8")

    engine = CounterEngine(persona_dir)
    metadata = {"mode": "freechat"}

    engine.ensure_mode(metadata["mode"])
    engine.increment_turn(metadata)
    trigger = engine.check_triggers(metadata)[0]

    assert engine.workspace == tmp_path
    assert engine.data_workspace == persona_dir
    assert engine.load_prompt(trigger) == "prompt"
    assert f"Workspace: {tmp_path}" in engine.build_task(trigger, str(persona_dir / "sessions" / "abc"))


def test_file_line_count_cursor_is_stored_under_persona_trigger(tmp_path: Path) -> None:
    trigger_file = tmp_path / "mode" / "default" / "trigger" / "triggers.json"
    trigger_file.parent.mkdir(parents=True)
    trigger_file.write_text(
        json.dumps(
            {
                "version": 1,
                "triggers": [
                    {
                        "id": "progress_tracker",
                        "enabled": True,
                        "condition": {
                            "kind": "file_line_count",
                            "count": 2,
                            "scope": "global",
                            "path": "persona/user_responses.jsonl",
                        },
                        "target": {"subagent": "progress_tracker"},
                        "cursor": {"offset": 0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "persona" / "user_responses.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text("{}\n{}\n", encoding="utf-8")

    engine = CounterEngine(tmp_path)
    firing = engine.check_triggers({})
    assert [trigger.id for trigger in firing] == ["progress_tracker"]

    engine.record_trigger({}, "progress_tracker")

    cursor_path = tmp_path / "persona" / "trigger" / "count" / ".cursor_progress_tracker.json"
    assert json.loads(cursor_path.read_text(encoding="utf-8"))["offset"] == 2
    unchanged = json.loads(trigger_file.read_text(encoding="utf-8"))
    assert unchanged["triggers"][0]["cursor"]["offset"] == 0
