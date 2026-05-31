import json
from pathlib import Path

from nanobot.cli.cron_utils import (
    build_session_note_deltas,
    build_session_thread_deltas,
    read_cursor_state,
    read_jsonl_delta,
    read_text_delta,
    write_cursor_state,
)


def _append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_read_jsonl_delta_advances_by_lines(tmp_path: Path) -> None:
    workspace = tmp_path
    source = workspace / "persona" / "sessions" / "s1" / "thread.jsonl"
    _append_jsonl(
        source,
        [
            {"role": "user", "content": {"text": "first"}},
            {"role": "assistant", "content": {"text": "reply"}},
        ],
    )

    state = read_cursor_state(workspace, "memory_cron")
    records, file_state = read_jsonl_delta(source, state)
    assert [r["role"] for r in records] == ["user", "assistant"]

    state["files"][str(source.resolve())] = file_state
    write_cursor_state(workspace, "memory_cron", state)
    _append_jsonl(source, [{"role": "user", "content": {"text": "second"}}])

    next_state = read_cursor_state(workspace, "memory_cron")
    records, file_state = read_jsonl_delta(source, next_state)
    assert len(records) == 1
    assert records[0]["content"]["text"] == "second"
    assert file_state["lines"] == 3


def test_read_text_delta_uses_byte_offset_and_handles_truncate(tmp_path: Path) -> None:
    workspace = tmp_path
    source = workspace / "persona" / "sessions" / "s1" / "notes" / "vocab.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("alpha\n", encoding="utf-8")

    state = read_cursor_state(workspace, "daily_consolidator")
    delta, file_state = read_text_delta(source, state)
    assert delta == "alpha\n"

    state["files"][str(source.resolve())] = file_state
    write_cursor_state(workspace, "daily_consolidator", state)
    with source.open("a", encoding="utf-8") as fh:
        fh.write("beta\n")

    next_state = read_cursor_state(workspace, "daily_consolidator")
    delta, file_state = read_text_delta(source, next_state)
    assert delta == "beta\n"

    next_state["files"][str(source.resolve())] = file_state
    write_cursor_state(workspace, "daily_consolidator", next_state)
    source.write_text("reset\n", encoding="utf-8")

    reset_state = read_cursor_state(workspace, "daily_consolidator")
    delta, file_state = read_text_delta(source, reset_state)
    assert delta == "reset\n"
    assert file_state["reset"] is True


def test_build_session_thread_deltas_prefers_persona_sessions(tmp_path: Path) -> None:
    workspace = tmp_path
    thread = workspace / "persona" / "sessions" / "s1" / "thread.jsonl"
    _append_jsonl(thread, [{"role": "user", "content": {"text": "hello"}}])

    deltas, cursor = build_session_thread_deltas(workspace, "memory_cron")
    assert len(deltas) == 1
    assert deltas[0]["thread_path"] == str(thread)
    assert deltas[0]["new_messages"][0]["content"]["text"] == "hello"

    write_cursor_state(workspace, "memory_cron", cursor)
    _append_jsonl(thread, [{"role": "assistant", "content": {"text": "hi"}}])

    deltas, cursor = build_session_thread_deltas(workspace, "memory_cron")
    assert len(deltas) == 1
    assert deltas[0]["new_line_count"] == 1
    assert deltas[0]["new_messages"][0]["role"] == "assistant"


def test_build_session_note_deltas_only_returns_appended_note_text(tmp_path: Path) -> None:
    workspace = tmp_path
    session_dir = workspace / "persona" / "sessions" / "s1"
    thread = session_dir / "thread.jsonl"
    vocab = session_dir / "notes" / "vocab.md"
    polisher = session_dir / "notes" / "polisher.md"
    _append_jsonl(thread, [{"role": "user", "content": {"text": "topic"}}])
    vocab.parent.mkdir(parents=True, exist_ok=True)
    vocab.write_text("- vivid\n", encoding="utf-8")
    polisher.write_text("- I am -> I'm\n", encoding="utf-8")

    deltas, cursor = build_session_note_deltas(workspace, "daily_consolidator")
    assert len(deltas) == 1
    assert deltas[0]["vocab_delta"] == "- vivid\n"
    assert deltas[0]["polisher_delta"] == "- I am -> I'm\n"

    write_cursor_state(workspace, "daily_consolidator", cursor)
    with vocab.open("a", encoding="utf-8") as fh:
        fh.write("- nuanced\n")

    deltas, _cursor = build_session_note_deltas(workspace, "daily_consolidator")
    assert len(deltas) == 1
    assert deltas[0]["vocab_delta"] == "- nuanced\n"
    assert deltas[0]["polisher_delta"] == ""
