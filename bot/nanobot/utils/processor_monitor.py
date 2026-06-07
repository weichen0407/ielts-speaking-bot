"""Processor cursor and run observability helpers."""

from __future__ import annotations

import json
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from nanobot.config.capabilities import monitor_log, project_root_for
from nanobot.utils.monitor_rotator import append_monitor_record


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def line_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open(encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _fingerprint_lines(lines: list[str]) -> str:
    payload = "\n".join(lines)
    if lines:
        payload += "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "input.jsonl"


@dataclass
class ProcessorDeltaInput:
    source_path: Path
    run_path: Path
    cursor_before: int
    cursor_after: int
    total_lines: int
    input_rows: int
    cursor_key: str
    input_fingerprint: str

    def to_record(self, root: Path) -> dict[str, Any]:
        rel_path = _safe_rel(root, self.source_path)
        return {
            "path": rel_path,
            "input_path": rel_path,
            "run_path": _safe_rel(root, self.run_path) if self.run_path.is_relative_to(root) else str(self.run_path),
            "cursor_before": self.cursor_before,
            "cursor_after": self.cursor_after,
            "last_line": self.cursor_after,
            "total_lines": self.total_lines,
            "input_rows": self.input_rows,
            "cursor_key": self.cursor_key,
            "input_fingerprint": self.input_fingerprint,
        }


@dataclass
class ProcessorDeltaBundle:
    run_paths: list[Path]
    inputs: list[ProcessorDeltaInput]
    temp_dir: TemporaryDirectory[str] | None = None
    cursor_kind: str = "none"
    processor_cursor_after: dict[str, int] | None = None

    @property
    def input_rows(self) -> int:
        return sum(item.input_rows for item in self.inputs)

    @property
    def cursor_before(self) -> dict[str, int]:
        return {item.cursor_key: item.cursor_before for item in self.inputs}

    @property
    def cursor_after(self) -> dict[str, int]:
        return {item.cursor_key: item.cursor_after for item in self.inputs}

    @property
    def cursor_records_after(self) -> dict[str, dict[str, Any]]:
        return {
            item.cursor_key: {
                "input_path": item.cursor_key,
                "last_line": item.cursor_after,
                "input_fingerprint": item.input_fingerprint,
            }
            for item in self.inputs
        }

    def cleanup(self) -> None:
        if self.temp_dir is not None:
            self.temp_dir.cleanup()


class ProcessorCursorStore:
    """Maintain per-trigger cursors for artifact processor inputs."""

    def __init__(self, root: Path) -> None:
        self.root = project_root_for(Path(root))
        self.cursor_dir = self.root / "persona" / "trigger" / "processor"

    def path_for(self, trigger_id: str) -> Path:
        return self.cursor_dir / f".cursor_{trigger_id}.json"

    def read(self, trigger_id: str) -> dict[str, int]:
        path = self.path_for(trigger_id)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        offsets = raw.get("offsets", raw)
        if not isinstance(offsets, dict):
            return {}
        result: dict[str, int] = {}
        for key, value in offsets.items():
            try:
                result[str(key)] = max(int(value), 0)
            except (TypeError, ValueError):
                continue
        return result

    def write(
        self,
        trigger_id: str,
        offsets: dict[str, int],
        *,
        inputs: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        path = self.path_for(trigger_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized_offsets = {key: max(int(value), 0) for key, value in offsets.items()}
        normalized_inputs: dict[str, dict[str, Any]] = {}
        for key, value in normalized_offsets.items():
            raw_input = inputs.get(key, {}) if inputs else {}
            normalized_inputs[key] = {
                "input_path": str(raw_input.get("input_path") or key),
                "last_line": value,
                "input_fingerprint": str(raw_input.get("input_fingerprint") or ""),
                "updated_at": _now_iso(),
            }
        payload = {
            "version": 2,
            "trigger_id": trigger_id,
            "updated_at": _now_iso(),
            "offsets": normalized_offsets,
            "inputs": normalized_inputs,
        }
        tmp_path = path.with_name(f".{path.name}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)


def materialize_processor_delta(
    *,
    root: Path,
    trigger_id: str,
    source_paths: list[Path],
    file_line_cursor: int | None = None,
) -> ProcessorDeltaBundle:
    """Create temporary JSONL files containing only unprocessed input rows.

    If *file_line_cursor* is provided, the caller owns cursor persistence
    through the file_line_count trigger. Otherwise this function uses the
    per-processor artifact cursor store.
    """
    root = project_root_for(Path(root))
    temp_dir = TemporaryDirectory(prefix="nanobot_processor_delta_")
    temp_root = Path(temp_dir.name)
    store = ProcessorCursorStore(root)
    stored_offsets = {} if file_line_cursor is not None else store.read(trigger_id)
    cursor_after = dict(stored_offsets)
    run_paths: list[Path] = []
    inputs: list[ProcessorDeltaInput] = []

    for index, source_path in enumerate(source_paths):
        source_path = Path(source_path)
        cursor_key = _safe_rel(root, source_path)
        lines = _read_lines(source_path)
        total = len(lines)
        before = int(file_line_cursor if file_line_cursor is not None else stored_offsets.get(cursor_key, 0))
        if before > total:
            before = 0
        delta_lines = lines[before:]
        run_path = temp_root / f"{index:02d}_{_sanitize_filename(source_path.name)}"
        run_path.write_text(
            "\n".join(delta_lines) + ("\n" if delta_lines else ""),
            encoding="utf-8",
        )
        run_paths.append(run_path)
        inputs.append(
            ProcessorDeltaInput(
                source_path=source_path,
                run_path=run_path,
                cursor_before=before,
                cursor_after=total,
                total_lines=total,
                input_rows=len(delta_lines),
                cursor_key=cursor_key,
                input_fingerprint=_fingerprint_lines(lines),
            )
        )
        if file_line_cursor is None:
            cursor_after[cursor_key] = total

    return ProcessorDeltaBundle(
        run_paths=run_paths,
        inputs=inputs,
        temp_dir=temp_dir,
        cursor_kind="file_line_count" if file_line_cursor is not None else "processor",
        processor_cursor_after=cursor_after if file_line_cursor is None else None,
    )


def update_processor_cursor(
    root: Path,
    trigger_id: str,
    offsets: dict[str, int],
    *,
    inputs: dict[str, dict[str, Any]] | None = None,
) -> None:
    ProcessorCursorStore(root).write(trigger_id, offsets, inputs=inputs)


def output_delta_records(path: Path, *, start_line: int, limit: int = 20) -> list[dict[str, Any]]:
    lines = _read_lines(path)
    delta = lines[start_line:]
    records: list[dict[str, Any]] = []
    for line in delta[:limit]:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = {"raw": line}
        if isinstance(parsed, dict):
            records.append(parsed)
        else:
            records.append({"value": parsed})
    return records


def append_processor_run(
    root: Path,
    *,
    trigger_id: str,
    processor: str,
    subagent: str | None = None,
    execution_mode: str | None = None,
    tools: list[str] | None = None,
    mode: str | None,
    session_key: str | None,
    session_uuid: str | None,
    status: str,
    model: str | None = None,
    input_paths: list[str] | None = None,
    output_path: str | None = None,
    artifact_paths: list[str] | None = None,
    cursor_kind: str | None = None,
    cursor_before: dict[str, Any] | None = None,
    cursor_after: dict[str, Any] | None = None,
    input_rows: int = 0,
    output_rows: int = 0,
    duration_ms: int = 0,
    usage: dict[str, Any] | None = None,
    output_preview: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    """Append one processor run to monitor/processor_runs.jsonl."""
    root = project_root_for(Path(root))
    monitor_dir, log_name = monitor_log(root, "processor_runs", "processor_runs.jsonl")
    artifacts = list(artifact_paths or [])
    if output_path and output_path not in artifacts:
        artifacts.append(output_path)
        md_path = str(Path(output_path).with_suffix(".md"))
        if md_path not in artifacts:
            artifacts.append(md_path)
    record = {
        "timestamp": _now_iso(),
        "trigger_id": trigger_id,
        "processor": processor,
        "subagent": subagent,
        "execution_mode": execution_mode,
        "tools": tools or [],
        "mode": mode,
        "session_key": session_key,
        "session_uuid": session_uuid,
        "status": status,
        "model": model,
        "input_paths": input_paths or [],
        "output_path": output_path,
        "artifact_paths": artifacts,
        "cursor_kind": cursor_kind,
        "cursor_before": cursor_before or {},
        "cursor_after": cursor_after or {},
        "input_rows": input_rows,
        "output_rows": output_rows,
        "duration_ms": duration_ms,
        "usage": usage or {},
        "output_preview": output_preview or [],
        "error": error,
    }
    append_monitor_record(monitor_dir, log_name, record)


def append_processor_subagent_run(
    root: Path,
    *,
    trigger_id: str,
    processor: str,
    subagent: str,
    execution_mode: str,
    task_id: str,
    mode: str | None,
    session_key: str | None,
    session_uuid: str | None,
    status: str,
    model: str | None = None,
    tools: list[str] | None = None,
    input_rows: int = 0,
    output_rows: int = 0,
    duration_ms: int = 0,
    usage: dict[str, Any] | None = None,
    result_preview: str | None = None,
    error: str | None = None,
) -> None:
    """Append a processor-mediated subagent execution to subagent_runs.jsonl."""
    root = project_root_for(Path(root))
    monitor_dir, log_name = monitor_log(root, "subagent_runs", "subagent_runs.jsonl")
    record = {
        "timestamp": _now_iso(),
        "task_id": task_id,
        "label": subagent,
        "subagent": subagent,
        "phase": "done" if status == "completed" else status,
        "model": model,
        "stop_reason": status,
        "error": error,
        "origin": {
            "kind": "processor_middleware",
            "trigger_id": trigger_id,
            "processor": processor,
            "mode": mode,
            "session_key": session_key,
            "session_uuid": session_uuid,
        },
        "task": f"{processor} middleware -> {subagent} ({execution_mode})",
        "result": result_preview,
        "usage": usage or {},
        "tool_events": [],
        "artifacts": [],
        "announce_result": False,
        "execution_mode": execution_mode,
        "tools": tools or [],
        "input_rows": input_rows,
        "output_rows": output_rows,
        "duration_ms": duration_ms,
    }
    append_monitor_record(monitor_dir, log_name, record)


__all__ = [
    "ProcessorCursorStore",
    "ProcessorDeltaBundle",
    "append_processor_run",
    "append_processor_subagent_run",
    "materialize_processor_delta",
    "output_delta_records",
    "update_processor_cursor",
    "line_count",
]
