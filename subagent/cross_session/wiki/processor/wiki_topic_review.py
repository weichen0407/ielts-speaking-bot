"""Review queue for taxonomy evolution candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TopicReviewItem:
    suggested_domain: str
    suggested_topic: str
    reason: str
    source_refs: list[str] = field(default_factory=list)
    sample_messages: list[str] = field(default_factory=list)
    evidence_count: int = 1
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_candidate(
        cls,
        data: dict[str, Any],
        *,
        source_refs: list[str],
        sample_messages: list[str],
    ) -> "TopicReviewItem | None":
        suggested_domain = str(data.get("suggested_domain") or "").strip()
        suggested_topic = str(data.get("suggested_topic") or "").strip()
        if not suggested_domain or not suggested_topic:
            return None
        now = _now_iso()
        return cls(
            suggested_domain=suggested_domain,
            suggested_topic=suggested_topic,
            reason=str(data.get("reason") or ""),
            source_refs=list(source_refs),
            sample_messages=list(sample_messages),
            evidence_count=max(1, len(source_refs)),
            created_at=now,
            updated_at=now,
        )

    def key(self) -> tuple[str, str]:
        return (self.suggested_domain, self.suggested_topic)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suggested_domain": self.suggested_domain,
            "suggested_topic": self.suggested_topic,
            "reason": self.reason,
            "source_refs": self.source_refs,
            "sample_messages": self.sample_messages,
            "evidence_count": self.evidence_count,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TopicReviewQueue:
    """Append/merge pending taxonomy evolution suggestions."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def upsert(self, item: TopicReviewItem) -> TopicReviewItem:
        items = self.load()
        now = _now_iso()
        for existing in items:
            if existing.key() != item.key() or existing.status != "pending":
                continue
            for ref in item.source_refs:
                if ref not in existing.source_refs:
                    existing.source_refs.append(ref)
            for message in item.sample_messages:
                if message not in existing.sample_messages:
                    existing.sample_messages.append(message)
            existing.evidence_count = max(existing.evidence_count, len(existing.source_refs))
            if item.reason and item.reason not in existing.reason:
                existing.reason = f"{existing.reason}; {item.reason}".strip("; ")
            existing.updated_at = now
            self.save(items)
            return existing

        items.append(item)
        self.save(items)
        return item

    def load(self) -> list[TopicReviewItem]:
        if not self.path.exists():
            return []
        items: list[TopicReviewItem] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            items.append(
                TopicReviewItem(
                    suggested_domain=str(data.get("suggested_domain") or ""),
                    suggested_topic=str(data.get("suggested_topic") or ""),
                    reason=str(data.get("reason") or ""),
                    source_refs=list(data.get("source_refs") or []),
                    sample_messages=list(data.get("sample_messages") or []),
                    evidence_count=int(data.get("evidence_count") or 1),
                    status=str(data.get("status") or "pending"),
                    created_at=str(data.get("created_at") or ""),
                    updated_at=str(data.get("updated_at") or ""),
                )
            )
        return items

    def save(self, items: list[TopicReviewItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now().isoformat()
