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
