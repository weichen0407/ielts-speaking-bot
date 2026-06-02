"""Topic taxonomy support for wiki memory extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TaxonomyTopic:
    domain: str
    topic: str
    description: str
    subtypes: tuple[str, ...]
    examples: tuple[str, ...]


@dataclass(frozen=True)
class TaxonomyFallback:
    domain: str = "other"
    topic: str = "uncategorized"
    subtype: str = "unknown"


class WikiTaxonomy:
    """Loaded topic taxonomy used to constrain LLM extraction."""

    def __init__(self, data: dict[str, Any]):
        self.version = int(data.get("version", 1))
        fallback = data.get("fallback") or {}
        self.fallback = TaxonomyFallback(
            domain=str(fallback.get("domain") or "other"),
            topic=str(fallback.get("topic") or "uncategorized"),
            subtype=str(fallback.get("subtype") or "unknown"),
        )
        self._domains = data.get("domains") or {}
        if not isinstance(self._domains, dict) or not self._domains:
            raise ValueError("wiki taxonomy must define at least one domain")

    @classmethod
    def load(cls, path: Path) -> "WikiTaxonomy":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError("wiki taxonomy root must be an object")
        taxonomy = cls(data)
        taxonomy.validate(
            taxonomy.fallback.domain,
            taxonomy.fallback.topic,
            taxonomy.fallback.subtype,
        )
        return taxonomy

    def has_domain(self, domain: str) -> bool:
        return domain in self._domains

    def has_topic(self, domain: str, topic: str) -> bool:
        domain_data = self._domains.get(domain) or {}
        topics = domain_data.get("topics") or {}
        return topic in topics

    def validate(self, domain: str, topic: str, subtype: str) -> bool:
        if not self.has_topic(domain, topic):
            return False
        topic_data = self._topic_data(domain, topic)
        subtypes = topic_data.get("subtypes") or []
        return subtype in subtypes

    def normalize(self, domain: str | None, topic: str | None, subtype: str | None) -> tuple[str, str, str]:
        domain = (domain or "").strip()
        topic = (topic or "").strip()
        subtype = (subtype or "").strip()
        if self.validate(domain, topic, subtype):
            return domain, topic, subtype
        return self.fallback.domain, self.fallback.topic, self.fallback.subtype

    def topic_path(self, domain: str, topic: str) -> str:
        return f"{domain}/{topic}"

    def iter_topics(self) -> list[TaxonomyTopic]:
        topics: list[TaxonomyTopic] = []
        for domain, domain_data in self._domains.items():
            domain_topics = domain_data.get("topics") or {}
            for topic, topic_data in domain_topics.items():
                topics.append(
                    TaxonomyTopic(
                        domain=domain,
                        topic=topic,
                        description=str(topic_data.get("description") or ""),
                        subtypes=tuple(str(s) for s in topic_data.get("subtypes") or []),
                        examples=tuple(str(e) for e in topic_data.get("examples") or []),
                    )
                )
        return topics

    def allowed_values_for_prompt(self) -> str:
        """Return a compact taxonomy block for the extractor prompt."""
        lines = [
            "Allowed taxonomy values. You must choose from these values exactly:",
            "",
        ]
        for topic in self.iter_topics():
            subtype_text = ", ".join(topic.subtypes)
            lines.append(f"- {topic.domain}/{topic.topic}: subtypes=[{subtype_text}]")
            if topic.description:
                lines.append(f"  description: {topic.description}")
            if topic.examples:
                lines.append(f"  examples: {'; '.join(topic.examples[:2])}")
        fallback = self.fallback
        lines.append("")
        lines.append(
            f"If nothing fits, use {fallback.domain}/{fallback.topic}/{fallback.subtype} "
            "and include candidate_new_topic."
        )
        return "\n".join(lines)

    def _topic_data(self, domain: str, topic: str) -> dict[str, Any]:
        domain_data = self._domains.get(domain) or {}
        topics = domain_data.get("topics") or {}
        topic_data = topics.get(topic) or {}
        return topic_data if isinstance(topic_data, dict) else {}


def default_taxonomy_path(workspace: Path) -> Path:
    workspace = Path(workspace)
    path = workspace / "config" / "wiki_taxonomy.yaml"
    if path.exists():
        return path
    return Path(__file__).resolve().parents[4] / "config" / "wiki_taxonomy.yaml"
