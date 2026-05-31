"""Append-only trigger decision monitor log."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.config.capabilities import monitor_log, project_root_for
from nanobot.utils.monitor_rotator import append_monitor_record


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_trigger_decision(
    workspace: Path,
    *,
    trigger_id: str,
    name: str | None = None,
    mode: str | None = None,
    session_key: str | None = None,
    session_uuid: str | None = None,
    kind: str | None = None,
    decision: str,
    reason: str,
    source: str | None = None,
    subagent: str | None = None,
    model: str | None = None,
    turn_count: int | None = None,
    cursor_before: dict[str, Any] | None = None,
    cursor_after: dict[str, Any] | None = None,
    subagent_task_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append one trigger decision to monitor/trigger_decisions.jsonl.

    This is best-effort observability. It must never break runtime behavior.
    """
    root = project_root_for(Path(workspace))
    monitor_dir, log_name = monitor_log(root, "trigger_decisions", "trigger_decisions.jsonl")
    record = {
        "timestamp": _now_iso(),
        "trigger_id": trigger_id,
        "name": name,
        "mode": mode,
        "session_key": session_key,
        "session_uuid": session_uuid,
        "kind": kind,
        "decision": decision,
        "reason": reason,
        "source": source,
        "subagent": subagent,
        "model": model,
        "turn_count": turn_count,
        "cursor_before": cursor_before or {},
        "cursor_after": cursor_after or {},
        "subagent_task_id": subagent_task_id,
        "details": details or {},
    }
    append_monitor_record(monitor_dir, log_name, record)
