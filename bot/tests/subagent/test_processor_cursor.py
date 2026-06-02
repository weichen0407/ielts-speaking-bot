import json
from pathlib import Path

from nanobot.utils.monitor_rotator import read_monitor_records
from nanobot.utils.processor_monitor import (
    ProcessorCursorStore,
    append_processor_run,
    materialize_processor_delta,
    update_processor_cursor,
)


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_processor_cursor_materializes_only_new_artifact_rows(tmp_path: Path) -> None:
    vocab = tmp_path / "persona" / "processor" / "freechat" / "vocab.jsonl"
    polisher = tmp_path / "persona" / "processor" / "freechat" / "polisher.jsonl"
    _append_jsonl(vocab, [{"original": "old vocab"}])
    _append_jsonl(polisher, [{"original": "old grammar"}])

    first = materialize_processor_delta(
        root=tmp_path,
        trigger_id="freechat_review_processor",
        source_paths=[vocab, polisher],
    )

    assert first.input_rows == 2
    assert [path.read_text(encoding="utf-8").count("\n") for path in first.run_paths] == [1, 1]
    update_processor_cursor(tmp_path, "freechat_review_processor", first.processor_cursor_after or {})
    first.cleanup()

    _append_jsonl(vocab, [{"original": "new vocab"}])

    second = materialize_processor_delta(
        root=tmp_path,
        trigger_id="freechat_review_processor",
        source_paths=[vocab, polisher],
    )

    assert second.input_rows == 1
    assert "new vocab" in second.run_paths[0].read_text(encoding="utf-8")
    assert second.run_paths[1].read_text(encoding="utf-8") == ""
    assert second.cursor_before == {
        "persona/processor/freechat/vocab.jsonl": 1,
        "persona/processor/freechat/polisher.jsonl": 1,
    }
    assert second.cursor_after == {
        "persona/processor/freechat/vocab.jsonl": 2,
        "persona/processor/freechat/polisher.jsonl": 1,
    }
    second.cleanup()


def test_processor_run_log_is_append_only(tmp_path: Path) -> None:
    append_processor_run(
        tmp_path,
        trigger_id="freechat_vocab_processor",
        processor="vocab",
        mode="freechat",
        session_key="web:1",
        session_uuid="session-1",
        status="completed",
        model="deepseek-v4-flash",
        input_paths=["persona/events/thread.jsonl"],
        output_path="persona/processor/freechat/vocab.jsonl",
        cursor_kind="file_line_count",
        cursor_before={"persona/events/thread.jsonl": 2},
        cursor_after={"persona/events/thread.jsonl": 4},
        input_rows=2,
        output_rows=1,
        duration_ms=123,
        usage={"prompt_tokens": 10, "completion_tokens": 5},
        output_preview=[{"original": "I like basketball very much."}],
    )

    records = read_monitor_records(tmp_path / "monitor", "processor_runs.jsonl")

    assert records[0]["processor"] == "vocab"
    assert records[0]["input_rows"] == 2
    assert records[0]["usage"]["prompt_tokens"] == 10


def test_processor_cursor_store_ignores_invalid_offsets(tmp_path: Path) -> None:
    store = ProcessorCursorStore(tmp_path)
    path = store.path_for("broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"offsets": {"ok.jsonl": 3, "bad.jsonl": "nope"}}),
        encoding="utf-8",
    )

    assert store.read("broken") == {"ok.jsonl": 3}
