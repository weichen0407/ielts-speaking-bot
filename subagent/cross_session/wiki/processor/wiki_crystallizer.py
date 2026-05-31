"""Crystallize ingest candidates into durable wiki patches."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .schema import WikiPatch, WikiSource
from .wiki_index import WikiIndex
from .wiki_ingest import WikiCandidate, WikiIngestAnalysis
from .wiki_query import WikiQueryEngine
from .wiki_store import WikiStore


@dataclass(frozen=True)
class CrystallizeResult:
    """Patches generated and optionally applied during crystallization."""

    patches: list[WikiPatch]
    applied: list[WikiPatch]


class WikiCrystallizer:
    """Turn analyzed candidates into sourced wiki pages."""

    def __init__(self, wiki_root: Path):
        self.wiki_root = Path(wiki_root)
        self.query = WikiQueryEngine(wiki_root=self.wiki_root)
        self.store = WikiStore(workspace=self.wiki_root.parent, wiki_root=self.wiki_root)
        self.index = WikiIndex(wiki_root=self.wiki_root)

    def to_patches(
        self,
        analysis: WikiIngestAnalysis,
        *,
        mode: str = "global",
        limit: int = 8,
    ) -> list[WikiPatch]:
        """Convert candidate signals into mergeable WikiPatch objects."""

        patches: list[WikiPatch] = []
        for candidate in analysis.candidates[:limit]:
            slug = self._choose_slug(candidate)
            section = _section_for_type(candidate.type)
            patches.append(
                WikiPatch(
                    operation="merge_section",
                    slug=slug,
                    title=candidate.title,
                    type=candidate.type,
                    mode=mode,
                    section=section,
                    content=candidate.content,
                    tags=candidate.tags,
                    topics=candidate.topics,
                    links=[],
                    sources=[_source_from_ref(ref) for ref in candidate.source_refs],
                    confidence=candidate.confidence,
                )
            )
        return patches

    def save_analysis(
        self,
        analysis: WikiIngestAnalysis,
        *,
        mode: str = "global",
        limit: int = 8,
    ) -> CrystallizeResult:
        """Generate and apply patches from an ingest analysis."""

        patches = self.to_patches(analysis, mode=mode, limit=limit)
        applied: list[WikiPatch] = []
        for patch in patches:
            if self.store.apply_patch(patch):
                self.index.index_page(patch.slug)
                applied.append(patch)
        return CrystallizeResult(patches=patches, applied=applied)

    def _choose_slug(self, candidate: WikiCandidate) -> str:
        existing = self.query.query(
            candidate.content,
            page_type=candidate.type,
            tags=candidate.tags or None,
            limit=1,
        )
        if existing and existing[0].score >= 2.0:
            return existing[0].slug
        return f"{candidate.type}/{_slugify(candidate.title)}"


def _section_for_type(page_type: str) -> str:
    return {
        "source": "Extracted Signals",
        "entity": "Known Facts",
        "concept": "Evidence",
        "comparison": "Differences",
        "question": "Context",
        "synthesis": "Supporting Evidence",
        "decision": "Rationale",
        "gap": "Missing Knowledge",
        "meta": "State",
    }.get(page_type, "Summary")


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    if not text:
        return f"untitled-{digest}"
    # Slug validator currently only allows latin letters/numbers and separators.
    ascii_text = re.sub(r"[^a-z0-9_-]+", "-", text)
    ascii_text = re.sub(r"-+", "-", ascii_text).strip("-")
    if not ascii_text:
        return f"item-{digest}"
    return f"{ascii_text[:70]}-{digest}"


def _source_from_ref(ref: str) -> WikiSource:
    parts = ref.split(":")
    if len(parts) >= 4 and parts[0] == "thread":
        return WikiSource(kind="thread", session_id=parts[1], message_id=":".join(parts[2:]))
    if len(parts) >= 3:
        return WikiSource(kind=parts[0], session_id=parts[1], message_id=":".join(parts[2:]))
    if len(parts) == 2:
        return WikiSource(kind=parts[0], session_id=parts[1])
    return WikiSource(kind=ref or "unknown")
