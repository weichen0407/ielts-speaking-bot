"""Deduplicate the derived unified interaction log.

The canonical conversation history is stored per session under
persona/sessions/<session_uuid>/thread.jsonl. persona/events/thread.jsonl is a derived
cross-session index used by processors and dashboards, so it is safe to rebuild
or compact when old append-only writes created duplicate rows.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def _record_key(record: dict[str, Any], fallback_index: int) -> tuple[str, str | int]:
    source = record.get("source")
    if isinstance(source, dict):
        session_uuid = source.get("session_uuid")
        message_index = source.get("message_index")
        if session_uuid and message_index is not None:
            return str(session_uuid), int(message_index)
    return "fallback", fallback_index


def _sort_key(record: dict[str, Any]) -> tuple[str, str, int]:
    source = record.get("source") if isinstance(record, dict) else {}
    if not isinstance(source, dict):
        source = {}
    try:
        message_index = int(source.get("message_index", 0) or 0)
    except (TypeError, ValueError):
        message_index = 0
    return (
        str(record.get("timestamp") or ""),
        str(source.get("session_uuid") or ""),
        message_index,
    )


def dedupe(path: Path) -> tuple[Path, int, int]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))

    compacted: dict[tuple[str, str | int], dict[str, Any]] = {}
    for index, record in enumerate(rows):
        key = _record_key(record, index)
        if key[0] != "fallback":
            record = dict(record)
            record["id"] = f"{key[0]}:{key[1]}"
        compacted[key] = record

    output = sorted(compacted.values(), key=_sort_key)
    backup = path.with_name(f"{path.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in output),
        encoding="utf-8",
    )
    return backup, len(rows), len(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        default="persona/events/thread.jsonl",
        help="Path to the derived JSONL log.",
    )
    args = parser.parse_args()

    backup, before, after = dedupe(Path(args.path))
    print(
        json.dumps(
            {
                "backup": str(backup),
                "before": before,
                "after": after,
                "removed": before - after,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
