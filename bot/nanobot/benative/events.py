"""Persistence helpers for Be Native response events."""

from __future__ import annotations

from pathlib import Path

from subagent._shared.benative_schema import BenativeResponse


def benative_responses_path(workspace: Path | str) -> Path:
    """Return the global Be Native response event log path."""
    return Path(workspace) / "persona" / "benative" / "events" / "responses.jsonl"


def append_benative_response(workspace: Path | str, response: BenativeResponse) -> Path:
    """Append one user reconstruction response to the global event log."""
    path = benative_responses_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(response.model_dump_json() + "\n")
    return path
