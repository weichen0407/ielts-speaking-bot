"""Ingest raw conversation deltas before crystallizing wiki pages."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from .wiki_layout import ensure_wiki_layout


CandidateType = Literal[
    "source",
    "entity",
    "concept",
    "comparison",
    "question",
    "synthesis",
    "decision",
    "gap",
    "meta",
]


@dataclass(frozen=True)
class IngestMessage:
    """One message extracted from the append-only thread stream."""

    line_no: int
    event_id: str
    session_id: str | None
    message_index: int | None
    role: str
    text: str
    timestamp: str | None
    raw: dict[str, Any]

    @property
    def source_ref(self) -> str:
        session = self.session_id or "global"
        return f"thread:{session}:{self.event_id or self.line_no}"


@dataclass(frozen=True)
class WikiCandidate:
    """A candidate signal extracted from raw messages."""

    type: CandidateType
    title: str
    content: str
    source_refs: list[str]
    confidence: Literal["low", "medium", "high"] = "medium"
    tags: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WikiIngestBatch:
    """Raw messages plus the source file that captured them."""

    source_id: str
    source_file: Path
    messages: list[IngestMessage]


@dataclass(frozen=True)
class WikiIngestAnalysis:
    """The result of step two of ingest: raw messages -> candidate signals."""

    batch: WikiIngestBatch
    candidates: list[WikiCandidate]


class WikiIngestor:
    """Load thread deltas and produce candidate signals.

    This class deliberately does not write crystallized wiki pages. It only
    persists raw evidence and returns structured candidates for query/save.
    """

    def __init__(self, workspace: Path, wiki_root: Path | None = None):
        self.workspace = Path(workspace)
        self.wiki_root = wiki_root or (self.workspace / "persona" / "wiki")
        self.layout = ensure_wiki_layout(self.wiki_root)

    def ingest_thread_delta(
        self,
        *,
        session_id: str | None = None,
        limit: int = 20,
        advance_cursor: bool = False,
        allowed_modes: set[str] | None = None,
    ) -> WikiIngestBatch:
        """Read new thread events, persist them under raw/thread, and return a batch."""

        thread_path = self.workspace / "persona" / "events" / "thread.jsonl"
        cursor = self._read_cursor()
        if session_id:
            per_session = cursor.get("thread_line_by_session")
            if not isinstance(per_session, dict):
                per_session = {}
            last_line = int(per_session.get(session_id, 0) or 0)
        else:
            last_line = int(cursor.get("thread_line", 0) or 0)
        messages: list[IngestMessage] = []

        if not thread_path.exists():
            return self._write_raw_batch([])

        with open(thread_path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                if line_no <= last_line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = self._message_from_event(line_no, event)
                if message is None:
                    continue
                if session_id and message.session_id != session_id:
                    continue
                if not _mode_allowed(message.raw, allowed_modes):
                    continue
                messages.append(message)

        if limit > 0:
            messages = messages[-limit:]

        batch = self._write_raw_batch(messages)
        if advance_cursor and messages:
            max_line = max(m.line_no for m in messages)
            if session_id:
                per_session = cursor.get("thread_line_by_session")
                if not isinstance(per_session, dict):
                    per_session = {}
                per_session[session_id] = max_line
                cursor["thread_line_by_session"] = per_session
            else:
                cursor["thread_line"] = max_line
            self._write_cursor(cursor)
        return batch

    def analyze(self, batch: WikiIngestBatch) -> WikiIngestAnalysis:
        """Extract simple deterministic candidate signals from an ingest batch."""

        candidates: list[WikiCandidate] = []
        if not batch.messages:
            return WikiIngestAnalysis(batch=batch, candidates=[])

        source_refs = [m.source_ref for m in batch.messages]
        user_text = "\n".join(m.text for m in batch.messages if m.role == "user").strip()
        all_text = "\n".join(m.text for m in batch.messages).strip()

        if all_text:
            candidates.append(
                WikiCandidate(
                    type="source",
                    title=f"Thread Source {batch.source_id}",
                    content=all_text[:2000],
                    source_refs=source_refs,
                    confidence="high",
                    tags=["thread"],
                    topics=[],
                )
            )

        for message in batch.messages:
            text = message.text.strip()
            if not text:
                continue
            lowered = text.lower()
            refs = [message.source_ref]

            if "?" in text or lowered.startswith(("why", "how", "what", "when", "where")):
                candidates.append(
                    WikiCandidate(
                        type="question",
                        title=_title_from_text(text, "Open Question"),
                        content=text,
                        source_refs=refs,
                        confidence="medium",
                        tags=["question"],
                    )
                )

            if any(token in lowered for token in ("decide", "decision", "决定", "按照", "采用")):
                candidates.append(
                    WikiCandidate(
                        type="decision",
                        title=_title_from_text(text, "Decision"),
                        content=text,
                        source_refs=refs,
                        confidence="medium",
                        tags=["decision"],
                    )
                )

            if any(token in lowered for token in ("gap", "missing", "不足", "缺口", "不确定")):
                candidates.append(
                    WikiCandidate(
                        type="gap",
                        title=_title_from_text(text, "Knowledge Gap"),
                        content=text,
                        source_refs=refs,
                        confidence="low",
                        tags=["gap"],
                    )
                )

        if user_text:
            candidates.append(
                WikiCandidate(
                    type="synthesis",
                    title="Recent User Signals",
                    content=user_text[:1200],
                    source_refs=[m.source_ref for m in batch.messages if m.role == "user"],
                    confidence="medium",
                    tags=["user-signal"],
                )
            )

        return WikiIngestAnalysis(batch=batch, candidates=_dedupe_candidates(candidates))

    def _message_from_event(self, line_no: int, event: dict[str, Any]) -> IngestMessage | None:
        role = event.get("role")
        if role not in {"user", "assistant", "subagent"}:
            return None
        content = event.get("content")
        if isinstance(content, dict):
            text = content.get("text", "")
        else:
            text = content or ""
        if not isinstance(text, str) or not text.strip():
            return None
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        return IngestMessage(
            line_no=line_no,
            event_id=str(event.get("id") or line_no),
            session_id=source.get("session_uuid"),
            message_index=source.get("message_index"),
            role=str(role),
            text=text.strip(),
            timestamp=event.get("timestamp"),
            raw=event,
        )

    def _write_raw_batch(self, messages: list[IngestMessage]) -> WikiIngestBatch:
        source_id = _now_id()
        source_file = self.layout.raw_thread_root / f"{source_id}.jsonl"
        if messages:
            with open(source_file, "w", encoding="utf-8") as f:
                for message in messages:
                    f.write(json.dumps(message.raw, ensure_ascii=False) + "\n")
        return WikiIngestBatch(source_id=source_id, source_file=source_file, messages=messages)

    def _read_cursor(self) -> dict[str, Any]:
        if not self.layout.ingest_cursor_path.exists():
            return {}
        try:
            return json.loads(self.layout.ingest_cursor_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write_cursor(self, data: dict[str, Any]) -> None:
        self.layout.ingest_cursor_path.parent.mkdir(parents=True, exist_ok=True)
        self.layout.ingest_cursor_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _now_id() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S-%f")


def _title_from_text(text: str, fallback: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return fallback
    return compact[:72].rstrip(" ,.;:!?") or fallback


def _dedupe_candidates(candidates: list[WikiCandidate]) -> list[WikiCandidate]:
    seen: set[tuple[str, str]] = set()
    deduped: list[WikiCandidate] = []
    for candidate in candidates:
        key = (candidate.type, candidate.content.lower().strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _mode_allowed(event: dict[str, Any], allowed_modes: set[str] | None) -> bool:
    if not allowed_modes:
        return True
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    mode = source.get("mode") or metadata.get("mode") or "freechat"
    return str(mode).lower() in allowed_modes
