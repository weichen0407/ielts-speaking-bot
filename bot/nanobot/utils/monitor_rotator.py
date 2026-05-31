"""Monitor log rotation: append-only JSONL files with size-based rotation.

Writes go to the active file (e.g. ``subagent_runs.jsonl``).  When the active
file exceeds ``_MAX_BYTES`` it is renamed with a timestamp suffix and a new
active file is created.  Old rotated files are pruned to keep at most
``_MAX_BACKUPS``.

Reads aggregate the active file plus rotated files, newest first, up to
*limit* records.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_MAX_BACKUPS = 10

_TS_RE = re.compile(r"-(\d{8})-(\d{6})\.jsonl$")


def _now_suffix() -> str:
    return datetime.now(timezone.utc).strftime("-%Y%m%d-%H%M%S")


def _parse_ts(filename: str) -> datetime | None:
    m = _TS_RE.search(filename)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _rotate_if_needed(monitor_dir: Path, active_name: str) -> None:
    active = monitor_dir / active_name
    if not active.exists() or active.stat().st_size < _MAX_BYTES:
        return
    rotated = monitor_dir / f"{active_name.replace('.jsonl', '')}{_now_suffix()}.jsonl"
    try:
        active.rename(rotated)
    except OSError:
        logger.debug("Failed to rotate monitor log {}", active)
        return

    # Prune old backups
    stem = active_name.replace(".jsonl", "")
    backups = [
        (p, ts)
        for p in monitor_dir.glob(f"{stem}-*.jsonl")
        if (ts := _parse_ts(p.name)) is not None
    ]
    backups.sort(key=lambda x: x[1], reverse=True)
    for old_path, _ in backups[_MAX_BACKUPS:]:
        try:
            old_path.unlink()
        except OSError:
            pass


def append_monitor_record(
    monitor_dir: Path,
    log_name: str,
    record: dict[str, Any],
) -> None:
    """Append a JSONL record to the active monitor log, rotating if necessary."""
    try:
        monitor_dir.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(monitor_dir, log_name)
        path = monitor_dir / log_name
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Monitor logging is best-effort observability; never break runtime.
        return


def read_monitor_records(
    monitor_dir: Path,
    log_name: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Read the newest *limit* records from the active log and rotated backups.

    Records are returned newest-first by file mtime (good-enough ordering for
    monitor UI).
    """
    records: list[dict[str, Any]] = []
    stem = log_name.replace(".jsonl", "")
    files: list[tuple[Path, float]] = []

    active = monitor_dir / log_name
    if active.exists():
        files.append((active, active.stat().st_mtime))

    for p in monitor_dir.glob(f"{stem}-*.jsonl"):
        if _parse_ts(p.name) is not None:
            files.append((p, p.stat().st_mtime))

    files.sort(key=lambda x: x[1], reverse=True)

    for path, _ in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    return records
    return records
