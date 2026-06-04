import json
from pathlib import Path

from nanobot.counter.types import CounterTrigger


def test_benative_triggers_run_review_once_per_response() -> None:
    root = Path(__file__).resolve().parents[3]
    config = json.loads((root / "mode" / "benative" / "trigger" / "triggers.json").read_text())

    triggers = [CounterTrigger.from_dict(row) for row in config["triggers"]]

    assert [trigger.id for trigger in triggers] == [
        "benative_article",
        "benative_vocab",
        "benative_polisher",
        "benative_review",
    ]

    by_id = {trigger.id: trigger for trigger in triggers}

    assert by_id["benative_article"].target.processor == "benative_article"
    assert by_id["benative_article"].target.subagent == "benative_article"
    assert by_id["benative_article"].target.input_path == "persona/benative/sources/index.jsonl"

    assert by_id["benative_vocab"].enabled is False

    assert by_id["benative_polisher"].enabled is False

    assert by_id["benative_review"].target.processor == "benative_review"
    assert by_id["benative_review"].target.depends_on is None
    assert by_id["benative_review"].condition.count == 1

    for trigger in triggers:
        assert trigger.condition.kind == "file_line_count"
        assert trigger.condition.count == 1
        assert trigger.target.execution_mode == "api"
        assert trigger.target.agentic is False
        assert trigger.target.tools == []
        assert trigger.target.model == "deepseek-v4-flash"
