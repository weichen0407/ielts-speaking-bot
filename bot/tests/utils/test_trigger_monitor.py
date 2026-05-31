import json
from pathlib import Path

from nanobot.utils.trigger_monitor import append_trigger_decision


def test_append_trigger_decision_writes_root_monitor_when_workspace_is_persona(tmp_path: Path) -> None:
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()

    append_trigger_decision(
        persona_dir,
        trigger_id="vocab_analysis",
        decision="skipped",
        reason="turn_count_not_due",
        mode="freechat",
    )

    path = tmp_path / "monitor" / "trigger_decisions.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    assert rows[0]["trigger_id"] == "vocab_analysis"
    assert rows[0]["decision"] == "skipped"
    assert not (persona_dir / "monitor" / "trigger_decisions.jsonl").exists()
