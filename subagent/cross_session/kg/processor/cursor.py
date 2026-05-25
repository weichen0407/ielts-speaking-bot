"""Cursor tracking for incremental processing."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SourceCursor:
    """Cursor state for a single source file."""
    processed_lines: int = 0
    last_timestamp: str | None = None


@dataclass
class KG_Cursor:
    """Cursor tracking for KG processing."""
    last_run: str | None = None
    sources: dict[str, SourceCursor] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_run": self.last_run,
            "sources": {
                name: {"processed_lines": s.processed_lines, "last_timestamp": s.last_timestamp}
                for name, s in self.sources.items()
            },
        }


class CursorManager:
    """
    Manages cursor state for KG processing.

    Cursor file: {data_dir}/.cursor.json
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.cursor_path = self.data_dir / ".cursor.json"
        self._cursor: KG_Cursor | None = None

    def read(self) -> KG_Cursor:
        """Read the current cursor state."""
        if self._cursor is not None:
            return self._cursor

        if not self.cursor_path.exists():
            self._cursor = KG_Cursor()
            return self._cursor

        with open(self.cursor_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._cursor = KG_Cursor(
            last_run=data.get("last_run"),
            sources={
                name: SourceCursor(**state)
                for name, state in data.get("sources", {}).items()
            },
        )
        return self._cursor

    def write(self, cursor: KG_Cursor) -> None:
        """Write cursor state to file."""
        self._cursor = cursor
        tmp_path = self.cursor_path.with_suffix(".json.tmp")

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cursor.to_dict(), f, ensure_ascii=False, indent=2)

        tmp_path.replace(self.cursor_path)

    def update_source(self, source: str, processed_lines: int, last_timestamp: str | None = None) -> None:
        """Update cursor for a specific source."""
        cursor = self.read()
        cursor.sources[source] = SourceCursor(
            processed_lines=processed_lines,
            last_timestamp=last_timestamp,
        )
        cursor.last_run = datetime.now(timezone.utc).isoformat()
        self.write(cursor)

    def get_source_cursor(self, source: str) -> SourceCursor:
        """Get cursor state for a specific source."""
        cursor = self.read()
        return cursor.sources.get(source, SourceCursor())

    def reset(self) -> None:
        """Reset cursor (for testing)."""
        self._cursor = KG_Cursor()
        if self.cursor_path.exists():
            self.cursor_path.unlink()
