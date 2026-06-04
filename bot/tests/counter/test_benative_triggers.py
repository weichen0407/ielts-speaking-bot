import json
from pathlib import Path

from nanobot.counter.types import CounterTrigger


def test_benative_triggers_register_four_middleware_subagents() -> None:
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

    assert by_id["benative_vocab"].target.processor == "vocab"
    assert by_id["benative_vocab"].target.subagent == "vocab"
    assert by_id["benative_vocab"].target.output_path == "persona/processor/benative/vocab.jsonl"

    assert by_id["benative_polisher"].target.processor == "polisher"
    assert by_id["benative_polisher"].target.depends_on == "benative_vocab"

    assert by_id["benative_review"].target.processor == "benative_review"
    assert by_id["benative_review"].target.depends_on == "benative_polisher"

    for trigger in triggers:
        assert trigger.condition.kind == "file_line_count"
        assert trigger.condition.count == 1
        assert trigger.target.execution_mode == "api"
        assert trigger.target.agentic is False
        assert trigger.target.tools == []
        assert trigger.target.model == "deepseek-v4-flash"
