"""Cron utilities: cursor management and incremental session discovery."""

from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any


CursorState = dict[str, Any]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _cursor_path(workspace: Path, trigger_id: str) -> Path:
    data_root = workspace if workspace.name == "persona" else workspace / "persona"
    return data_root / "trigger" / "cron" / f".cursor_{trigger_id}.json"


def _file_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _file_mtime(path: Path) -> str:
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime.isoformat().replace("+00:00", "Z")


def read_cursor_state(workspace: Path, trigger_id: str) -> CursorState:
    """Read the full cursor state for a cron trigger."""
    cursor_path = _cursor_path(workspace, trigger_id)
    if not cursor_path.exists():
        return {"files": {}}
    try:
        data = json.loads(cursor_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {"files": {}}
    if not isinstance(data, dict):
        return {"files": {}}
    if not isinstance(data.get("files"), dict):
        data["files"] = {}
    return data


def write_cursor_state(
    workspace: Path,
    trigger_id: str,
    state: CursorState,
    timestamp: str | None = None,
) -> None:
    """Write the full cursor state for a cron trigger.

    The timestamp is updated on each successful cron pass. File offsets are
    advanced by callers only after the corresponding subagent completed.
    """
    if timestamp is None:
        timestamp = _utc_now_iso()
    state = dict(state)
    state["last_processed_timestamp"] = timestamp
    state.setdefault("files", {})
    cursor_path = _cursor_path(workspace, trigger_id)
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    cursor_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_time_cursor(workspace: Path, trigger_id: str) -> str | None:
    """Read last_processed_timestamp from cursor file.

    Returns None if cursor doesn't exist (first run).
    """
    return read_cursor_state(workspace, trigger_id).get("last_processed_timestamp")


def write_time_cursor(workspace: Path, trigger_id: str, timestamp: str | None = None) -> None:
    """Write new cursor timestamp.

    If timestamp is None, uses current UTC time.
    """
    write_cursor_state(
        workspace,
        trigger_id,
        read_cursor_state(workspace, trigger_id),
        timestamp=timestamp,
    )


def resolve_sessions_dir(workspace: Path) -> Path:
    """Return the active sessions directory for either root or persona workspace."""
    candidates = [
        workspace / "persona" / "sessions",
        workspace / "sessions",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _list_all_sessions(sessions_dir: Path) -> list[dict]:
    """List all sessions in the sessions directory."""
    sessions = []
    if not sessions_dir.exists():
        return sessions
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        thread_path = session_dir / "thread.jsonl"
        if not thread_path.exists():
            continue
        try:
            with open(thread_path, encoding="utf-8") as f:
                first_line = f.readline()
            metadata = json.loads(first_line)
            mtime = datetime.fromtimestamp(thread_path.stat().st_mtime, tz=timezone.utc)
            sessions.append({
                "path": str(session_dir),
                "uuid": session_dir.name,
                "topic": metadata.get("metadata", {}).get("title", ""),
                "updated_at": mtime.isoformat().replace("+00:00", "Z"),
            })
        except (json.JSONDecodeError, IOError):
            continue
    return sessions


def find_modified_sessions(sessions_dir: Path, since_timestamp: str | None) -> list[dict]:
    """Find sessions with thread.jsonl modified since timestamp.

    If since_timestamp is None, returns all sessions (first run).
    """
    if since_timestamp is None:
        return _list_all_sessions(sessions_dir)

    # Parse timestamp, handle both Z suffix and +00:00
    since_str = since_timestamp.replace("Z", "+00:00")
    since_dt = datetime.fromisoformat(since_str).astimezone(timezone.utc)

    modified = []
    if not sessions_dir.exists():
        return modified

    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        thread_path = session_dir / "thread.jsonl"
        if not thread_path.exists():
            continue

        mtime_dt = datetime.fromtimestamp(thread_path.stat().st_mtime, tz=timezone.utc)
        if mtime_dt <= since_dt:
            continue

        try:
            with open(thread_path, encoding="utf-8") as f:
                first_line = f.readline()
            metadata = json.loads(first_line)
            modified.append({
                "path": str(session_dir),
                "uuid": session_dir.name,
                "topic": metadata.get("metadata", {}).get("title", ""),
                "updated_at": mtime_dt.isoformat().replace("+00:00", "Z"),
            })
        except (json.JSONDecodeError, IOError):
            continue

    return modified


def find_sessions_with_modified_notes(
    sessions_dir: Path,
    since_timestamp: str | None,
) -> list[dict]:
    """Find sessions where vocab.md or polisher.md was modified since timestamp.

    If since_timestamp is None, returns all sessions with notes (first run).
    """
    since_dt = None
    if since_timestamp is not None:
        since_str = since_timestamp.replace("Z", "+00:00")
        since_dt = datetime.fromisoformat(since_str).astimezone(timezone.utc)

    modified = []
    if not sessions_dir.exists():
        return modified

    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        notes_dir = session_dir / "notes"
        if not notes_dir.exists():
            continue

        vocab_path = notes_dir / "vocab.md"
        polisher_path = notes_dir / "polisher.md"

        latest_mtime = None
        latest_path = None
        for path in [vocab_path, polisher_path]:
            if path.exists():
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_path = path

        if latest_mtime is None:
            continue
        if since_dt is not None and latest_mtime <= since_dt:
            continue

        modified.append({
            "path": str(session_dir),
            "uuid": session_dir.name,
            "vocab_path": str(vocab_path) if vocab_path.exists() else None,
            "polisher_path": str(polisher_path) if polisher_path.exists() else None,
            "updated_at": latest_mtime.isoformat().replace("+00:00", "Z"),
        })

    return modified


def read_jsonl_delta(
    path: Path,
    state: CursorState,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read JSONL records appended after the cursor's processed line count."""
    files = state.setdefault("files", {})
    key = _file_key(path)
    previous = files.get(key, {}) if isinstance(files.get(key), dict) else {}
    start_line = int(previous.get("lines", 0) or 0)

    records: list[dict[str, Any]] = []
    total_lines = 0
    reset = False
    if not path.exists():
        return records, {"lines": 0, "bytes": 0, "exists": False}

    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh):
            total_lines = line_no + 1
            if total_lines < start_line:
                continue
            if total_lines == start_line and start_line > 0:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = {"_raw": stripped, "_parse_error": "invalid_json"}
            if isinstance(parsed, dict):
                parsed.setdefault("_source_line", total_lines)
                records.append(parsed)
            else:
                records.append({"value": parsed, "_source_line": total_lines})

    if total_lines < start_line:
        reset = True
        records = []
        total_lines = 0
        with path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh):
                total_lines = line_no + 1
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    parsed = {"_raw": stripped, "_parse_error": "invalid_json"}
                if isinstance(parsed, dict):
                    parsed.setdefault("_source_line", total_lines)
                    records.append(parsed)
                else:
                    records.append({"value": parsed, "_source_line": total_lines})

    file_state: dict[str, Any] = {
        "lines": total_lines,
        "bytes": path.stat().st_size,
        "mtime": _file_mtime(path),
    }
    if reset:
        file_state["reset"] = True
    return records, file_state


def read_text_delta(
    path: Path,
    state: CursorState,
) -> tuple[str, dict[str, Any]]:
    """Read text appended after the cursor's processed byte offset."""
    files = state.setdefault("files", {})
    key = _file_key(path)
    previous = files.get(key, {}) if isinstance(files.get(key), dict) else {}
    start_byte = int(previous.get("bytes", 0) or 0)

    if not path.exists():
        return "", {"bytes": 0, "exists": False}

    size = path.stat().st_size
    reset = False
    if size < start_byte:
        start_byte = 0
        reset = True

    with path.open("rb") as fh:
        fh.seek(start_byte)
        delta = fh.read().decode("utf-8", errors="replace")

    file_state: dict[str, Any] = {
        "bytes": size,
        "mtime": _file_mtime(path),
    }
    if reset:
        file_state["reset"] = True
    return delta, file_state


def build_session_thread_deltas(
    workspace: Path,
    trigger_id: str,
    sessions_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], CursorState]:
    """Build memory-cron payloads containing only new thread.jsonl records."""
    state = read_cursor_state(workspace, trigger_id)
    sessions_dir = sessions_dir or resolve_sessions_dir(workspace)
    # Scan session headers every cron pass and let per-file line cursors decide
    # what is new. This avoids missing writes that land while a cron subagent is
    # still running but before the timestamp cursor is advanced.
    sessions = _list_all_sessions(sessions_dir)
    pending = dict(state)
    pending["files"] = dict(state.get("files", {}))

    deltas: list[dict[str, Any]] = []
    for session in sessions:
        thread_path = Path(session["path"]) / "thread.jsonl"
        records, file_state = read_jsonl_delta(thread_path, state)
        pending["files"][_file_key(thread_path)] = file_state
        if not records:
            continue
        deltas.append({
            **session,
            "thread_path": str(thread_path),
            "new_line_count": len(records),
            "new_messages": records,
        })
    return deltas, pending


def build_session_note_deltas(
    workspace: Path,
    trigger_id: str,
    sessions_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], CursorState]:
    """Build daily-consolidator payloads containing only appended note text."""
    state = read_cursor_state(workspace, trigger_id)
    sessions_dir = sessions_dir or resolve_sessions_dir(workspace)
    # Same race-avoidance as thread deltas: scan candidate note files, process
    # only appended bytes according to per-file cursors.
    sessions = find_sessions_with_modified_notes(
        sessions_dir,
        None,
    )
    pending = dict(state)
    pending["files"] = dict(state.get("files", {}))

    deltas: list[dict[str, Any]] = []
    for session in sessions:
        entry = dict(session)
        has_delta = False
        for field, delta_field in [
            ("vocab_path", "vocab_delta"),
            ("polisher_path", "polisher_delta"),
        ]:
            raw_path = entry.get(field)
            if not raw_path:
                entry[delta_field] = ""
                continue
            note_path = Path(raw_path)
            delta, file_state = read_text_delta(note_path, state)
            pending["files"][_file_key(note_path)] = file_state
            entry[delta_field] = delta
            if delta.strip():
                has_delta = True
        if has_delta:
            deltas.append(entry)
    return deltas, pending
