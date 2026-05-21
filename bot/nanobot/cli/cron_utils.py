"""Cron utilities: time-based cursor management and session discovery."""

from datetime import datetime, timezone
from pathlib import Path
import json


def read_time_cursor(workspace: Path, trigger_id: str) -> str | None:
    """Read last_processed_timestamp from cursor file.

    Returns None if cursor doesn't exist (first run).
    """
    cursor_path = workspace / "trigger" / "cron" / f".cursor_{trigger_id}.json"
    if cursor_path.exists():
        try:
            data = json.loads(cursor_path.read_text(encoding="utf-8"))
            return data.get("last_processed_timestamp")
        except (json.JSONDecodeError, IOError):
            return None
    return None


def write_time_cursor(workspace: Path, trigger_id: str, timestamp: str | None = None) -> None:
    """Write new cursor timestamp.

    If timestamp is None, uses current UTC time.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cursor_path = workspace / "trigger" / "cron" / f".cursor_{trigger_id}.json"
    cursor_path.write_text(
        json.dumps({"last_processed_timestamp": timestamp}, ensure_ascii=False),
        encoding="utf-8",
    )


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
    if since_timestamp is None:
        all_sessions = _list_all_sessions(sessions_dir)
        return [s for s in all_sessions if Path(s["path"] + "/notes").exists()]

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

        if latest_mtime is None or latest_mtime <= since_dt:
            continue

        modified.append({
            "path": str(session_dir),
            "uuid": session_dir.name,
            "vocab_path": str(vocab_path) if vocab_path.exists() else None,
            "polisher_path": str(polisher_path) if polisher_path.exists() else None,
            "updated_at": latest_mtime.isoformat().replace("+00:00", "Z"),
        })

    return modified
