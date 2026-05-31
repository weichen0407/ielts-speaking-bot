"""Hybrid local query for wiki pages.

The first version combines SQLite FTS with a lightweight Markdown scan and
link/topic expansion. It is intentionally local and deterministic so ingest
and save can ask "what do we already know?" before writing.
"""

from __future__ import annotations

import re
from pathlib import Path

from .schema import WikiSearchResult
from .wiki_search import WikiSearch
from .wiki_store import WikiStore, _split_sections


class WikiQueryEngine:
    """Search crystallized wiki pages with simple hybrid ranking."""

    def __init__(self, wiki_root: Path):
        self.wiki_root = Path(wiki_root)
        self.search = WikiSearch(wiki_root=self.wiki_root)
        self.store = WikiStore(workspace=self.wiki_root.parent, wiki_root=self.wiki_root)

    def query(
        self,
        query: str,
        *,
        mode: str | None = None,
        topic: str | None = None,
        page_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[WikiSearchResult]:
        """Return de-duplicated ranked results from FTS plus page scanning."""

        fts_results = self.search.search(
            query=query,
            mode=mode,
            topic=topic,
            page_type=page_type,
            tags=tags,
            limit=limit,
        )
        by_slug: dict[str, WikiSearchResult] = {r.slug: r for r in fts_results}

        for result in self._scan_pages(
            query=query,
            mode=mode,
            topic=topic,
            page_type=page_type,
            tags=tags,
            limit=limit * 2,
        ):
            existing = by_slug.get(result.slug)
            if existing is None or result.score > existing.score:
                by_slug[result.slug] = result

        expanded = self._expand_neighbors(list(by_slug.values()), mode=mode, page_type=page_type)
        for result in expanded:
            by_slug.setdefault(result.slug, result)

        return sorted(by_slug.values(), key=lambda r: r.score, reverse=True)[:limit]

    def _scan_pages(
        self,
        *,
        query: str,
        mode: str | None,
        topic: str | None,
        page_type: str | None,
        tags: list[str] | None,
        limit: int,
    ) -> list[WikiSearchResult]:
        terms = _terms(query)
        if not terms:
            return []

        results: list[WikiSearchResult] = []
        for meta in self.store.list_pages():
            if mode and meta.mode != mode:
                continue
            if page_type and meta.type != page_type:
                continue
            if topic and topic not in meta.topics:
                continue
            if tags and not all(tag in meta.tags for tag in tags):
                continue
            page = self.store.read_page(meta.slug)
            if not page:
                continue
            _, body = page
            haystack = " ".join(
                [
                    meta.slug,
                    meta.title,
                    meta.type,
                    " ".join(meta.tags),
                    " ".join(meta.topics),
                    " ".join(meta.aliases),
                    body,
                ]
            ).lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits == 0:
                continue
            section, snippet = _best_section(body, terms)
            title_boost = 2.0 if any(term in meta.title.lower() for term in terms) else 0.0
            tag_boost = 1.5 if any(term in " ".join(meta.tags).lower() for term in terms) else 0.0
            results.append(
                WikiSearchResult(
                    slug=meta.slug,
                    title=meta.title,
                    type=meta.type,
                    mode=meta.mode,
                    section=section,
                    snippet=snippet,
                    score=float(hits) + title_boost + tag_boost,
                    tags=meta.tags,
                    topics=meta.topics,
                )
            )

        return sorted(results, key=lambda r: r.score, reverse=True)[:limit]

    def _expand_neighbors(
        self,
        seeds: list[WikiSearchResult],
        *,
        mode: str | None,
        page_type: str | None,
    ) -> list[WikiSearchResult]:
        neighbors: list[WikiSearchResult] = []
        seen = {seed.slug for seed in seeds}
        for seed in seeds[:5]:
            page = self.store.read_page(seed.slug)
            if not page:
                continue
            meta, _ = page
            for link in meta.links[:5]:
                if link in seen:
                    continue
                linked = self.store.read_page(link)
                if not linked:
                    continue
                linked_meta, linked_body = linked
                if mode and linked_meta.mode != mode:
                    continue
                if page_type and linked_meta.type != page_type:
                    continue
                section, snippet = _best_section(linked_body, [])
                neighbors.append(
                    WikiSearchResult(
                        slug=linked_meta.slug,
                        title=linked_meta.title,
                        type=linked_meta.type,
                        mode=linked_meta.mode,
                        section=section,
                        snippet=snippet,
                        score=max(seed.score * 0.4, 0.1),
                        tags=linked_meta.tags,
                        topics=linked_meta.topics,
                    )
                )
                seen.add(link)
        return neighbors


def _terms(query: str) -> list[str]:
    return [
        term.lower()
        for term in re.split(r"[\s,.;:!?()\[\]{}\"']+", query)
        if len(term.strip()) >= 2
    ]


def _best_section(body: str, terms: list[str]) -> tuple[str, str]:
    sections = _split_sections(body)
    best_name = ""
    best_content = ""
    best_hits = -1
    for name, content in sections.items():
        lowered = content.lower()
        hits = sum(1 for term in terms if term in lowered) if terms else 0
        if hits > best_hits:
            best_name = name or "Summary"
            best_content = content
            best_hits = hits
    snippet = re.sub(r"\s+", " ", best_content).strip()[:400]
    return best_name or "Summary", snippet
