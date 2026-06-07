"""Persistence helpers for Be Native response events."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from subagent._shared.benative_schema import BenativeResponse


def benative_responses_path(workspace: Path | str) -> Path:
    """Return the global Be Native response event log path."""
    return Path(workspace) / "persona" / "benative" / "events" / "responses.jsonl"


def benative_session_dir(workspace: Path | str, session_uuid: str) -> Path:
    """Return the per-session Be Native directory."""
    return Path(workspace) / "persona" / "benative" / "sessions" / session_uuid


def benative_session_responses_path(workspace: Path | str, session_uuid: str) -> Path:
    """Return the per-session Be Native response event log path."""
    return benative_session_dir(workspace, session_uuid) / "responses.jsonl"


def append_benative_response(workspace: Path | str, response: BenativeResponse) -> Path:
    """Append one user reconstruction response to the global event log."""
    path = benative_responses_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(response.model_dump_json() + "\n")
    return path


def refresh_benative_session_summary(
    workspace: Path | str,
    session_uuid: str,
    *,
    article_id: str | None = None,
    total_sentences: int | None = None,
    current_sentence: int | None = None,
) -> Path:
    """Write a session-local summary for WebUI and monitor reads."""
    session_dir = benative_session_dir(workspace, session_uuid)
    session_dir.mkdir(parents=True, exist_ok=True)
    summary_path = session_dir / "summary.json"
    existing = _read_json(summary_path)

    responses_path = session_dir / "responses.jsonl"
    review_path = session_dir / "notes" / "review.jsonl"
    review_md_path = session_dir / "notes" / "review.md"
    responses = _read_jsonl(responses_path)
    reviews = _read_jsonl(review_path)

    response_sentence_indexes = _sentence_indexes(responses)
    review_sentence_indexes = _sentence_indexes(reviews)
    completed_sentence_indexes = sorted(set(response_sentence_indexes) | set(review_sentence_indexes))

    inferred_article_id = (
        article_id
        or _first_string(responses, "article_id")
        or _first_string(reviews, "article_id")
        or existing.get("article_id")
    )
    inferred_total = (
        total_sentences
        if total_sentences is not None
        else _as_int(existing.get("total_sentences"))
    )
    inferred_current = (
        current_sentence
        if current_sentence is not None
        else max(completed_sentence_indexes, default=-1) + 1
    )

    response_count = len(responses)
    review_count = len(reviews)
    if not completed_sentence_indexes:
        latest_review_status = "none"
    elif review_sentence_indexes and set(response_sentence_indexes).issubset(set(review_sentence_indexes)):
        latest_review_status = "reviewed"
    elif review_count:
        latest_review_status = "partial"
    else:
        latest_review_status = "pending"

    summary: dict[str, Any] = {
        "session_uuid": session_uuid,
        "article_id": inferred_article_id,
        "current_sentence": inferred_current,
        "total_sentences": inferred_total,
        "completed_sentence_indexes": completed_sentence_indexes,
        "response_count": response_count,
        "review_count": review_count,
        "latest_review_status": latest_review_status,
        "responses_path": _rel_artifact_path(responses_path, workspace),
        "review_path": _rel_artifact_path(review_path, workspace),
        "review_markdown_path": _rel_artifact_path(review_md_path, workspace),
        "updated_at": datetime.now().isoformat(),
    }

    tmp = summary_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(summary_path)
    return summary_path


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _sentence_indexes(rows: list[dict[str, Any]]) -> list[int]:
    indexes: list[int] = []
    for row in rows:
        value = _as_int(row.get("sentence_index"))
        if value is not None:
            indexes.append(value)
    return indexes


def _first_string(rows: list[dict[str, Any]], key: str) -> str | None:
    for row in rows:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _rel_artifact_path(path: Path, workspace: Path | str) -> str:
    try:
        return str(path.relative_to(Path(workspace)))
    except ValueError:
        return str(path)
