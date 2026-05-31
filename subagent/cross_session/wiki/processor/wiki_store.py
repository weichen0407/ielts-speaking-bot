"""WikiStore - canonical Markdown wiki store with patch application.

Pages are stored as Markdown files with YAML frontmatter.
Sources metadata is stored in companion .sources.json sidecar files.
All patch events are appended to log.jsonl.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import yaml

from .schema import (
    ALLOWED_OPERATIONS,
    WikiPageMeta,
    WikiPatch,
    WikiSource,
    WikiSourcesData,
    WikiSourcesEntry,
)
from .wiki_layout import WikiLayout, ensure_wiki_layout


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from Markdown content.

    Returns (frontmatter_dict, body_without_frontmatter).
    Raises ValueError if frontmatter is malformed.
    """
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw
    yaml_content = m.group(1)
    body = raw[m.end() :]
    try:
        data = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid frontmatter: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"Frontmatter must be a dict, got {type(data).__name__}")
    return dict(data), body


def _render_frontmatter(meta: WikiPageMeta) -> str:
    """Render frontmatter from WikiPageMeta as a YAML string."""
    obj = {
        "slug": meta.slug,
        "title": meta.title,
        "type": meta.type,
        "mode": meta.mode,
        "status": meta.status,
        "tags": meta.tags,
        "topics": meta.topics,
        "aliases": meta.aliases,
        "entities": meta.entities,
        "concepts": meta.concepts,
        "links": meta.links,
        "sources": meta.sources,
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
        "last_reviewed_at": meta.last_reviewed_at,
        "confidence": meta.confidence,
        "stability": meta.stability,
        "version": meta.version,
    }
    yaml_str = yaml.safe_dump(obj, default_flow_style=False, sort_keys=False, allow_unicode=True)
    # yaml.safe_dump produces clean YAML; strip any leading '---'
    yaml_str = yaml_str.lstrip("-").lstrip("\n")
    return f"---\n{yaml_str}---\n\n"


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^(#{1,6})\s+(.+)\s*$", re.MULTILINE)


def _find_section_heading(body: str, section: str) -> int | None:
    """Return the character index of the heading for `section`, or None."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m and m.group(2).strip() == section:
            # Return byte offset in original string
            prefix = "\n".join(lines[:i]) + ("\n" if i > 0 else "")
            return len(prefix.encode("utf-8"))
    return None


def _split_sections(body: str) -> dict[str, str]:
    """Split body text into sections by ## headings.

    Returns {section_name: section_content}.
    The 'Summary' section or first unnamed section gets key ''.
    """
    lines = body.splitlines()
    sections: dict[str, list[str]] = {}
    current: list[str] = []
    current_name = ""

    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+)\s*$", line)
        if m:
            if current or current_name == "":
                sections[current_name] = "\n".join(current).rstrip("\n")
            current = []
            current_name = m.group(2).strip()
        else:
            stripped = line.rstrip("\n")
            if stripped:
                current.append(stripped)

    sections[current_name] = "\n".join(current).rstrip("\n")
    return sections


def _normalize_bullet(text: str) -> str:
    """Normalize a bullet line for deduplication: lowercase + strip punctuation."""
    text = text.strip()
    # Remove leading bullet markers
    text = re.sub(r"^[-*+]\s+", "", text)
    # Lowercase
    text = text.lower()
    # Strip trailing punctuation
    text = text.rstrip(".,;:!?")
    # Strip leading/trailing whitespace
    text = text.strip()
    return text


def _bullet_sort_key(line: str) -> str:
    """Sort key for bullet lines to keep order stable."""
    stripped = line.strip()
    has_bullet = bool(re.match(r"^[-*+]\s+", stripped))
    return ("" if has_bullet else " ", stripped.lower())


# ---------------------------------------------------------------------------
# WikiStore
# ---------------------------------------------------------------------------


class WikiStore:
    """Persistent wiki page store backed by Markdown files.

    Wiki root layout::

        {wiki_root}/
            raw/                  # source evidence
            wiki/
                {type}/{slug}.md  # crystallized pages
            index/                # derived search index
            state/                # cursors and queues
            schema/               # validation contracts
            log.jsonl             # machine patch events
    """

    def __init__(self, workspace: Path, wiki_root: Path | None = None):
        self.workspace = Path(workspace)
        self.wiki_root = wiki_root or (self.workspace / "persona" / "wiki")
        self.layout: WikiLayout = ensure_wiki_layout(self.wiki_root)
        self.pages_root = self.layout.pages_root
        self._legacy_pages_root = self.wiki_root / "pages"
        self._log_path = self.wiki_root / "log.jsonl"
        self._ensure_dirs()

    # -- Path helpers --------------------------------------------------------

    def _ensure_dirs(self) -> None:
        ensure_wiki_layout(self.wiki_root)

    def page_path(self, slug: str) -> Path:
        """Return the path for a page, validated against traversal."""
        # Validate slug before constructing path
        from .schema import _validate_slug

        _validate_slug(slug)
        path = self.pages_root / f"{slug}.md"
        resolved = path.resolve()
        if not str(resolved).startswith(str(self.pages_root.resolve())):
            raise ValueError(f"Path traversal attempt: {slug}")
        return path

    def legacy_page_path(self, slug: str) -> Path:
        """Return the page path used by the initial wiki prototype."""
        from .schema import _validate_slug

        _validate_slug(slug)
        path = self._legacy_pages_root / f"{slug}.md"
        resolved = path.resolve()
        if not str(resolved).startswith(str(self._legacy_pages_root.resolve())):
            raise ValueError(f"Path traversal attempt: {slug}")
        return path

    def sources_path(self, slug: str) -> Path:
        """Return the companion sources.json path for a slug."""
        from .schema import _validate_slug

        _validate_slug(slug)
        path = self.pages_root / f"{slug}.sources.json"
        resolved = path.resolve()
        if not str(resolved).startswith(str(self.pages_root.resolve())):
            raise ValueError(f"Path traversal attempt: {slug}")
        return path

    # -- Read ----------------------------------------------------------------

    def read_page(self, slug: str) -> tuple[WikiPageMeta, str] | None:
        """Read a page by slug.

        Returns (meta, body) or None if not found.
        """
        path = self.page_path(slug)
        if not path.exists():
            legacy_path = self.legacy_page_path(slug)
            if legacy_path.exists():
                path = legacy_path
            else:
                return None
        raw = path.read_text(encoding="utf-8")
        try:
            fm_dict, body = _parse_frontmatter(raw)
        except ValueError:
            # Malformed frontmatter — treat as raw page with no meta
            fm_dict = {"slug": slug}
            body = raw
        meta = WikiPageMeta(
            slug=slug,
            title=fm_dict.get("title", slug),
            type=fm_dict.get("type") or "ielts_topic",
            mode=fm_dict.get("mode") or "ielts",
            tags=list(fm_dict.get("tags", [])),
            topics=list(fm_dict.get("topics", [])),
            aliases=list(fm_dict.get("aliases", [])),
            entities=list(fm_dict.get("entities", [])),
            concepts=list(fm_dict.get("concepts", [])),
            links=list(fm_dict.get("links", [])),
            sources=list(fm_dict.get("sources", [])),
            created_at=fm_dict.get("created_at") or fm_dict.get("updated_at", ""),
            updated_at=fm_dict.get("updated_at", ""),
            last_reviewed_at=fm_dict.get("last_reviewed_at"),
            confidence=fm_dict.get("confidence", "medium"),
            stability=fm_dict.get("stability", "volatile"),
            version=int(fm_dict.get("version", 1) or 1),
        )
        return meta, body.lstrip("\n")

    def read_sources(self, slug: str) -> WikiSourcesData | None:
        """Read the companion sources.json for a slug, or None if not found."""
        path = self.sources_path(slug)
        if not path.exists():
            legacy_path = self._legacy_pages_root / f"{slug}.sources.json"
            if legacy_path.exists():
                path = legacy_path
            else:
                return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return WikiSourcesData.model_validate(data)
        except (json.JSONDecodeError, ValueError):
            return None

    # -- Write ----------------------------------------------------------------

    def write_page(self, meta: WikiPageMeta, body: str) -> None:
        """Atomically write a page: write to .tmp then rename."""
        path = self.page_path(meta.slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        fm = _render_frontmatter(meta)
        content = f"{fm}{body.lstrip('\n')}\n"
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    def write_sources(self, slug: str, data: WikiSourcesData) -> None:
        """Atomically write the companion sources.json."""
        path = self.sources_path(slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".sources.json.tmp")
        tmp.write_text(
            data.model_dump_json(indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)

    # -- Log -----------------------------------------------------------------

    def append_log(self, event: dict) -> None:
        """Append one event dict to log.jsonl."""
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # -- Patch application ----------------------------------------------------

    def apply_patch(self, patch: WikiPatch) -> bool:
        """Apply a single WikiPatch.

        Returns True on success, False on rejection.
        Rejected patches are still logged.
        """
        try:
            return self._apply_patch_impl(patch)
        except Exception as e:
            self.append_log({
                "event": "patch_rejected",
                "slug": patch.slug,
                "operation": patch.operation,
                "error": str(e),
                "timestamp": _now_iso(),
            })
            return False

    def _apply_patch_impl(self, patch: WikiPatch) -> bool:
        now = _now_iso()

        # Read existing page
        existing = self.read_page(patch.slug)
        if existing:
            meta, body = existing
        else:
            # Create from patch defaults
            meta = WikiPageMeta(
                slug=patch.slug,
                title=patch.title,
                type=patch.type,
                mode=patch.mode,
                tags=list(patch.tags),
                topics=list(patch.topics),
                links=list(patch.links),
                sources=_source_refs(patch.sources),
                created_at=now,
                updated_at=now,
                confidence=patch.confidence,
            )
            body = ""

        # Apply operation
        if patch.operation == "create_page":
            self._op_create_page(meta, body, patch, now)
        elif patch.operation == "merge_section":
            self._op_merge_section(meta, body, patch, now)
        elif patch.operation == "append_section":
            self._op_append_section(meta, body, patch, now)
        elif patch.operation == "replace_section":
            self._op_replace_section(meta, body, patch, now)
        elif patch.operation == "add_link":
            self._op_add_link(meta, body, patch, now)
        elif patch.operation == "deprecate_fact":
            self._op_deprecate_fact(meta, body, patch, now)
        elif patch.operation == "update_summary":
            self._op_update_summary(meta, body, patch, now)
        else:
            raise ValueError(f"Unknown operation: {patch.operation}")

        # Log success
        self.append_log({
            "event": "patch_applied",
            "slug": patch.slug,
            "operation": patch.operation,
            "section": patch.section,
            "timestamp": now,
        })
        return True

    # -- Operation handlers ---------------------------------------------------

    def _op_create_page(self, meta: WikiPageMeta, body: str, patch: WikiPatch, now: str) -> None:
        """Create a new page if it doesn't exist."""
        if self.read_page(patch.slug) is not None:
            # Page exists — treat as merge
            self._op_merge_section(meta, body, patch, now)
            return
        meta.updated_at = now
        sections = self._default_sections(patch)
        body = self._build_body(sections)
        self.write_page(meta, body)
        self.write_sources(patch.slug, WikiSourcesData(facts={}))

    def _op_merge_section(
        self, meta: WikiPageMeta, body: str, patch: WikiPatch, now: str
    ) -> None:
        """Add content to a section with deduplication."""
        section = patch.section or "Summary"
        sources_data = self.read_sources(patch.slug) or WikiSourcesData(facts={})

        # Parse existing sections
        sections = _split_sections(body)

        # Normalize incoming fact key
        fact_key = patch.normalized_fact_key(patch.content)

        # Check if this fact already exists
        existing_entry: WikiSourcesEntry | None = None
        for key, entry in sources_data.facts.items():
            if key == fact_key and entry.section == section:
                existing_entry = entry
                break

        if existing_entry is not None:
            # Merge sources — do not add duplicate bullet
            for src in patch.sources:
                already_listed = any(
                    s.kind == src.kind
                    and s.session_id == src.session_id
                    and s.message_id == src.message_id
                    for s in existing_entry.sources
                )
                if not already_listed:
                    existing_entry.sources.append(src)
            existing_entry.confirmations += 1
            existing_entry.last_seen = now
        else:
            # Add new bullet to section
            sections = _split_sections(body)
            existing_lines = sections.get(section, "").splitlines()
            new_bullet = f"- {patch.content}"
            # Check for duplicate by normalized form
            normalized_new = _normalize_bullet(new_bullet)
            is_dup = any(
                _normalize_bullet(line) == normalized_new
                for line in existing_lines
            )
            if not is_dup:
                if sections.get(section):
                    sections[section] += f"\n{new_bullet}"
                else:
                    sections[section] = new_bullet
                body = self._build_body(sections)

            # Create sources entry
            sources_data.facts[fact_key] = WikiSourcesEntry(
                text=patch.content,
                section=section,
                sources=list(patch.sources),
                confirmations=1,
                first_seen=now,
                last_seen=now,
            )

        meta.updated_at = now
        # Merge tags/topics/links
        for t in patch.tags:
            if t not in meta.tags:
                meta.tags.append(t)
        for t in patch.topics:
            if t not in meta.topics:
                meta.topics.append(t)
        for l in patch.links:
            if l not in meta.links:
                meta.links.append(l)
        for source_ref in _source_refs(patch.sources):
            if source_ref not in meta.sources:
                meta.sources.append(source_ref)

        self.write_page(meta, body)
        self.write_sources(patch.slug, sources_data)

    def _op_append_section(
        self, meta: WikiPageMeta, body: str, patch: WikiPatch, now: str
    ) -> None:
        """Append content without deduplication (for timeline pages)."""
        section = patch.section or "Log"
        sections = _split_sections(body)
        bullet = f"- {patch.content}"
        if sections.get(section):
            sections[section] += f"\n{bullet}"
        else:
            sections[section] = bullet
        body = self._build_body(sections)

        sources_data = self.read_sources(patch.slug) or WikiSourcesData(facts={})
        fact_key = f"{patch.normalized_fact_key(patch.content)}:{now}"
        sources_data.facts[fact_key] = WikiSourcesEntry(
            text=patch.content,
            section=section,
            sources=list(patch.sources),
            confirmations=1,
            first_seen=now,
            last_seen=now,
        )

        meta.updated_at = now
        for source_ref in _source_refs(patch.sources):
            if source_ref not in meta.sources:
                meta.sources.append(source_ref)
        self.write_page(meta, body)
        self.write_sources(patch.slug, sources_data)

    def _op_replace_section(
        self, meta: WikiPageMeta, body: str, patch: WikiPatch, now: str
    ) -> None:
        """Replace a section entirely."""
        if not patch.reason:
            raise ValueError("replace_section requires a reason")
        section = patch.section or "Summary"
        sections = _split_sections(body)
        sections[section] = patch.content
        body = self._build_body(sections)
        meta.updated_at = now
        for source_ref in _source_refs(patch.sources):
            if source_ref not in meta.sources:
                meta.sources.append(source_ref)
        self.write_page(meta, body)
        # Note: replace_section does not touch sources.json since it replaces whole section

    def _op_add_link(
        self, meta: WikiPageMeta, body: str, patch: WikiPatch, now: str
    ) -> None:
        """Add links to page frontmatter."""
        for link in patch.links:
            if link not in meta.links:
                meta.links.append(link)
        meta.updated_at = now
        for source_ref in _source_refs(patch.sources):
            if source_ref not in meta.sources:
                meta.sources.append(source_ref)
        self.write_page(meta, body)

    def _op_deprecate_fact(
        self, meta: WikiPageMeta, body: str, patch: WikiPatch, now: str
    ) -> None:
        """Mark a fact as deprecated in sources.json and prepend '(deprecated)' in body."""
        sources_data = self.read_sources(patch.slug)
        if sources_data:
            fact_key = patch.normalized_fact_key(patch.content)
            for key, entry in list(sources_data.facts.items()):
                if key == fact_key:
                    # Rename key to mark deprecated
                    deprecated_key = f"__deprecated_{key}"
                    sources_data.facts[deprecated_key] = entry
                    del sources_data.facts[key]
                    # Update body: prepend (deprecated) to bullet
                    sections = _split_sections(body)
                    sec_content = sections.get(entry.section, "")
                    lines = sec_content.splitlines()
                    new_lines = []
                    for line in lines:
                        if _normalize_bullet(line) == _normalize_bullet(entry.text):
                            line = re.sub(
                                r"^([-*+]\s*)",
                                r"\1[DEPRECATED] ",
                                line,
                                count=1,
                            )
                        new_lines.append(line)
                    sections[entry.section] = "\n".join(new_lines)
                    body = self._build_body(sections)
                    self.write_sources(patch.slug, sources_data)
        meta.updated_at = now
        self.write_page(meta, body)

    def _op_update_summary(
        self, meta: WikiPageMeta, body: str, patch: WikiPatch, now: str
    ) -> None:
        """Replace only the ## Summary section."""
        sections = _split_sections(body)
        sections["Summary"] = patch.content
        body = self._build_body(sections)
        meta.updated_at = now
        for source_ref in _source_refs(patch.sources):
            if source_ref not in meta.sources:
                meta.sources.append(source_ref)
        self.write_page(meta, body)

    # -- Helpers --------------------------------------------------------------

    def _default_sections(self, patch: WikiPatch) -> dict[str, str]:
        """Return default section structure for a newly created page."""
        sections: dict[str, str] = {"Summary": ""}
        if patch.type == "source":
            sections["Raw Reference"] = ""
            sections["Extracted Signals"] = ""
        elif patch.type == "entity":
            sections["Identity"] = ""
            sections["Known Facts"] = ""
            sections["Open Questions"] = ""
        elif patch.type == "concept":
            sections["Definition"] = ""
            sections["Evidence"] = ""
            sections["Related"] = ""
        elif patch.type == "comparison":
            sections["Compared Items"] = ""
            sections["Similarities"] = ""
            sections["Differences"] = ""
            sections["Decision Relevance"] = ""
        elif patch.type == "question":
            sections["Question"] = ""
            sections["Context"] = ""
            sections["Possible Answers"] = ""
        elif patch.type == "synthesis":
            sections["Insight"] = ""
            sections["Supporting Evidence"] = ""
            sections["Implications"] = ""
        elif patch.type == "decision":
            sections["Decision"] = ""
            sections["Rationale"] = ""
            sections["Consequences"] = ""
        elif patch.type == "gap":
            sections["Missing Knowledge"] = ""
            sections["Why It Matters"] = ""
            sections["Research Plan"] = ""
        elif patch.type == "meta":
            sections["Purpose"] = ""
            sections["Rules"] = ""
            sections["State"] = ""
        return sections

    def _build_body(self, sections: dict[str, str]) -> str:
        """Build Markdown body from section dict, preserving order and blank lines."""
        lines: list[str] = []
        for name, content in sections.items():
            if name == "":
                # Unnamed first section — no heading
                if content.strip():
                    lines.append(content.strip())
            else:
                lines.append(f"## {name}")
                if content.strip():
                    lines.append(content.strip())
                lines.append("")
        return "\n\n".join(lines) + "\n"

    def list_pages(self) -> list[WikiPageMeta]:
        """Return metadata for all pages."""
        pages: list[WikiPageMeta] = []
        if not self.pages_root.exists():
            return pages
        for md_file in self.pages_root.rglob("*.md"):
            slug = str(md_file.relative_to(self.pages_root))[:-3].replace("\\", "/")
            result = self.read_page(slug)
            if result:
                pages.append(result[0])
        if self._legacy_pages_root.exists():
            seen = {page.slug for page in pages}
            for md_file in self._legacy_pages_root.rglob("*.md"):
                slug = str(md_file.relative_to(self._legacy_pages_root))[:-3].replace("\\", "/")
                if slug in seen:
                    continue
                result = self.read_page(slug)
                if result:
                    pages.append(result[0])
        return pages


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def _source_refs(sources: list[WikiSource]) -> list[str]:
    """Return stable frontmatter source refs for detailed sidecar sources."""
    refs: list[str] = []
    for source in sources:
        if source.message_id and source.session_id:
            ref = f"{source.kind}:{source.session_id}:{source.message_id}"
        elif source.session_id:
            ref = f"{source.kind}:{source.session_id}"
        elif source.file:
            ref = f"{source.kind}:{source.file}"
        else:
            ref = source.kind
        if ref not in refs:
            refs.append(ref)
    return refs
