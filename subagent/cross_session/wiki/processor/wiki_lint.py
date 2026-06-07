"""Structural and semantic linting for the LLM wiki."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .schema import ALLOWED_MEMORY_STATUSES, ALLOWED_PAGE_TYPES, WikiPageMeta
from .wiki_store import WikiStore, _parse_frontmatter


LintSeverity = Literal["info", "warning", "error"]
LintLayer = Literal["structure", "semantic"]


@dataclass(frozen=True)
class WikiLintFinding:
    """One lint finding."""

    layer: LintLayer
    severity: LintSeverity
    slug: str
    code: str
    message: str


class WikiLinter:
    """Run structural and semantic checks over wiki pages."""

    def __init__(self, wiki_root: Path):
        self.wiki_root = Path(wiki_root)
        self.store = WikiStore(workspace=self.wiki_root.parent, wiki_root=self.wiki_root)

    def lint(self) -> list[WikiLintFinding]:
        findings: list[WikiLintFinding] = []
        pages = self.store.list_pages()
        by_slug = {page.slug: page for page in pages}

        findings.extend(self._lint_files())
        findings.extend(self._lint_page_meta(pages, by_slug))
        findings.extend(self._lint_semantics(pages))
        return findings

    def _lint_files(self) -> list[WikiLintFinding]:
        findings: list[WikiLintFinding] = []
        if not self.store.pages_root.exists():
            return findings
        for md_file in self.store.pages_root.rglob("*.md"):
            slug = str(md_file.relative_to(self.store.pages_root))[:-3].replace("\\", "/")
            raw = md_file.read_text(encoding="utf-8")
            try:
                fm, _ = _parse_frontmatter(raw)
            except ValueError as exc:
                findings.append(
                    WikiLintFinding(
                        layer="structure",
                        severity="error",
                        slug=slug,
                        code="invalid_frontmatter",
                        message=str(exc),
                    )
                )
                continue
            missing = [
                key
                for key in ("slug", "title", "type", "mode", "status", "sources", "updated_at")
                if key not in fm
            ]
            if missing:
                findings.append(
                    WikiLintFinding(
                        layer="structure",
                        severity="error",
                        slug=slug,
                        code="missing_frontmatter_fields",
                        message=f"Missing frontmatter fields: {', '.join(missing)}",
                    )
                )
            if "memory_status" not in fm:
                findings.append(
                    WikiLintFinding(
                        layer="structure",
                        severity="warning",
                        slug=slug,
                        code="missing_memory_status",
                        message="Page frontmatter has no memory_status; defaulting to new.",
                    )
                )
        return findings

    def _lint_page_meta(
        self,
        pages: list[WikiPageMeta],
        by_slug: dict[str, WikiPageMeta],
    ) -> list[WikiLintFinding]:
        findings: list[WikiLintFinding] = []
        for page in pages:
            if page.type not in ALLOWED_PAGE_TYPES:
                findings.append(
                    WikiLintFinding(
                        layer="structure",
                        severity="error",
                        slug=page.slug,
                        code="invalid_type",
                        message=f"Unknown page type: {page.type}",
                    )
                )
            if page.memory_status not in ALLOWED_MEMORY_STATUSES:
                findings.append(
                    WikiLintFinding(
                        layer="structure",
                        severity="error",
                        slug=page.slug,
                        code="invalid_memory_status",
                        message=f"Unknown memory_status: {page.memory_status}",
                    )
                )
            for link in page.links:
                if link not in by_slug:
                    findings.append(
                        WikiLintFinding(
                            layer="structure",
                            severity="warning",
                            slug=page.slug,
                            code="broken_link",
                            message=f"Link target does not exist: {link}",
                        )
                    )
            if page.type not in {"meta", "gap", "question"} and not page.sources:
                findings.append(
                    WikiLintFinding(
                        layer="semantic",
                        severity="warning",
                        slug=page.slug,
                        code="no_frontmatter_sources",
                        message="Fact-bearing page has no source refs in frontmatter.",
                    )
                )
            for source in page.sources:
                if not source or source == "unknown" or source.endswith(":unknown"):
                    findings.append(
                        WikiLintFinding(
                            layer="semantic",
                            severity="warning",
                            slug=page.slug,
                            code="weak_source_ref",
                            message=f"Page has a weak source ref: {source}",
                        )
                    )
            sidecar = self.store.read_sources(page.slug)
            if page.type not in {"meta", "gap", "question"} and sidecar is None:
                findings.append(
                    WikiLintFinding(
                        layer="structure",
                        severity="warning",
                        slug=page.slug,
                        code="missing_sources_sidecar",
                        message="Fact-bearing page has no .sources.json sidecar.",
                    )
                )
            if sidecar is not None:
                for fact_key, fact in sidecar.facts.items():
                    if not fact.sources:
                        findings.append(
                            WikiLintFinding(
                                layer="semantic",
                                severity="warning",
                                slug=page.slug,
                                code="fact_missing_sources",
                                message=f"Fact has no source refs in sidecar: {fact_key}",
                            )
                        )
        return findings

    def _lint_semantics(self, pages: list[WikiPageMeta]) -> list[WikiLintFinding]:
        findings: list[WikiLintFinding] = []
        title_map: dict[str, list[WikiPageMeta]] = {}
        for page in pages:
            title_map.setdefault(_norm(page.title), []).append(page)
        for _, grouped in title_map.items():
            if len(grouped) <= 1:
                continue
            slugs = ", ".join(page.slug for page in grouped)
            for page in grouped:
                findings.append(
                    WikiLintFinding(
                        layer="semantic",
                        severity="warning",
                        slug=page.slug,
                        code="possible_duplicate",
                        message=f"Pages share a normalized title: {slugs}",
                    )
                )

        for page in pages:
            read = self.store.read_page(page.slug)
            if not read:
                continue
            _, body = read
            lowered = body.lower()
            if any(token in lowered for token in ("contradiction", "conflict", "矛盾", "冲突")):
                findings.append(
                    WikiLintFinding(
                        layer="semantic",
                        severity="warning",
                        slug=page.slug,
                        code="possible_conflict",
                        message="Page mentions a possible contradiction/conflict and should be reviewed.",
                    )
                )
            if page.type in {"entity", "concept"} and _looks_like_schema_projection(lowered):
                findings.append(
                    WikiLintFinding(
                        layer="semantic",
                        severity="warning",
                        slug=page.slug,
                        code="schema_projection_noise",
                        message="Entity/concept page appears to contain internal wiki schema labels.",
                    )
                )
            if page.type == "decision" and page.status == "active" and not page.last_reviewed_at:
                findings.append(
                    WikiLintFinding(
                        layer="semantic",
                        severity="info",
                        slug=page.slug,
                        code="decision_needs_review",
                        message="Active decision has not been reviewed yet.",
                    )
                )
        return findings


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _looks_like_schema_projection(text: str) -> bool:
    schema_terms = {
        "source",
        "entity",
        "concept",
        "comparison",
        "question",
        "synthesis",
        "decision",
        "gap",
        "meta",
    }
    hits = sum(1 for term in schema_terms if re.search(rf"\b{term}\b", text))
    return hits >= 5
