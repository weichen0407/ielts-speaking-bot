"""Tests for monitor log rotation utilities."""

import json
from pathlib import Path

import pytest

from nanobot.utils.monitor_rotator import (
    _MAX_BACKUPS,
    _MAX_BYTES,
    _parse_ts,
    append_monitor_record,
    read_monitor_records,
)


class TestAppendMonitorRecord:
    def test_creates_active_file(self, tmp_path: Path) -> None:
        monitor_dir = tmp_path / "monitor"
        append_monitor_record(monitor_dir, "test.jsonl", {"a": 1})
        active = monitor_dir / "test.jsonl"
        assert active.exists()
        lines = active.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"a": 1}

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        monitor_dir = tmp_path / "monitor"
        append_monitor_record(monitor_dir, "test.jsonl", {"a": 1})
        append_monitor_record(monitor_dir, "test.jsonl", {"b": 2})
        lines = (monitor_dir / "test.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1]) == {"b": 2}

    def test_rotates_when_size_exceeded(self, tmp_path: Path) -> None:
        monitor_dir = tmp_path / "monitor"
        active = monitor_dir / "test.jsonl"
        # Pre-fill active file to exceed the limit so rotation triggers
        payload = "x" * (_MAX_BYTES + 100)
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text(json.dumps({"payload": payload}) + "\n", encoding="utf-8")
        assert active.stat().st_size > _MAX_BYTES

        # This append should trigger rotation
        append_monitor_record(monitor_dir, "test.jsonl", {"next": True})

        # Active file should exist and contain only the new record
        assert active.exists()
        lines = active.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"next": True}

        # A rotated backup should exist
        backups = list(monitor_dir.glob("test-*.jsonl"))
        assert len(backups) == 1

    def test_prunes_old_backups(self, tmp_path: Path) -> None:
        monitor_dir = tmp_path / "monitor"
        monitor_dir.mkdir(parents=True, exist_ok=True)
        # Create more backups than allowed
        for i in range(_MAX_BACKUPS + 3):
            backup = monitor_dir / f"test-20260101-{i:06d}.jsonl"
            backup.write_text(json.dumps({"idx": i}) + "\n", encoding="utf-8")

        # Trigger rotation to prune
        active = monitor_dir / "test.jsonl"
        active.write_text("x" * (_MAX_BYTES + 1), encoding="utf-8")
        append_monitor_record(monitor_dir, "test.jsonl", {"new": True})

        backups = sorted(monitor_dir.glob("test-*.jsonl"))
        assert len(backups) == _MAX_BACKUPS

    def test_no_crash_on_permission_error(self, tmp_path: Path) -> None:
        # Best-effort: must not raise even on failure
        append_monitor_record(Path("/nonexistent/path"), "test.jsonl", {"a": 1})


class TestReadMonitorRecords:
    def test_reads_active_file(self, tmp_path: Path) -> None:
        monitor_dir = tmp_path / "monitor"
        append_monitor_record(monitor_dir, "test.jsonl", {"a": 1})
        append_monitor_record(monitor_dir, "test.jsonl", {"b": 2})
        records = read_monitor_records(monitor_dir, "test.jsonl", limit=10)
        assert len(records) == 2
        assert records[0] == {"b": 2}
        assert records[1] == {"a": 1}

    def test_reads_rotated_backups(self, tmp_path: Path) -> None:
        monitor_dir = tmp_path / "monitor"
        monitor_dir.mkdir(parents=True, exist_ok=True)
        # Create a rotated backup
        backup = monitor_dir / "test-20260101-120000.jsonl"
        backup.write_text(
            json.dumps({"old": 1}) + "\n" + json.dumps({"old": 2}) + "\n",
            encoding="utf-8",
        )
        # Create active file
        active = monitor_dir / "test.jsonl"
        active.write_text(json.dumps({"new": 3}) + "\n", encoding="utf-8")

        records = read_monitor_records(monitor_dir, "test.jsonl", limit=10)
        # Active file is newer (higher mtime), so it comes first
        assert len(records) == 3
        assert records[0] == {"new": 3}

    def test_respects_limit(self, tmp_path: Path) -> None:
        monitor_dir = tmp_path / "monitor"
        for i in range(5):
            append_monitor_record(monitor_dir, "test.jsonl", {"idx": i})
        records = read_monitor_records(monitor_dir, "test.jsonl", limit=2)
        assert len(records) == 2

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        monitor_dir = tmp_path / "monitor"
        monitor_dir.mkdir(parents=True, exist_ok=True)
        active = monitor_dir / "test.jsonl"
        active.write_text(
            json.dumps({"ok": 1}) + "\nnot json\n" + json.dumps({"ok": 2}) + "\n",
            encoding="utf-8",
        )
        records = read_monitor_records(monitor_dir, "test.jsonl", limit=10)
        assert len(records) == 2
        assert records[0] == {"ok": 2}
        assert records[1] == {"ok": 1}

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        records = read_monitor_records(tmp_path / "monitor", "test.jsonl", limit=10)
        assert records == []


class TestParseTimestamp:
    def test_valid_timestamp(self) -> None:
        dt = _parse_ts("subagent_runs-20260101-120000.jsonl")
        assert dt is not None
        assert dt.year == 2026
        assert dt.month == 1
        assert dt.day == 1
        assert dt.hour == 12
        assert dt.minute == 0
        assert dt.second == 0

    def test_invalid_timestamp_returns_none(self) -> None:
        assert _parse_ts("subagent_runs-2026-01-01.jsonl") is None
        assert _parse_ts("subagent_runs.jsonl") is None
