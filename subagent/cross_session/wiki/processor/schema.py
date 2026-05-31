"""Wiki Schema - Pydantic models for the LLM Wiki Memory System."""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Allowed page types
# ---------------------------------------------------------------------------

ALLOWED_PAGE_TYPES: set[str] = {
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

ALLOWED_MODES: set[str] = {"global", "ielts", "freechat", "benative", "language"}

ALLOWED_OPERATIONS: set[str] = {
    "create_page",
    "merge_section",
    "append_section",
    "replace_section",
    "add_link",
    "deprecate_fact",
    "update_summary",
}

LEGACY_PAGE_TYPE_MAP: dict[str, str] = {
    "user_profile": "entity",
    "user_preference": "concept",
    "user_goal": "concept",
    "communication_style": "concept",
    "ielts_topic": "concept",
    "ielts_question_bank": "question",
    "ielts_speaking_example": "source",
    "language_weakness": "concept",
    "expression_bank": "concept",
    "freechat_project": "entity",
    "freechat_interest": "concept",
    "benative_article_learning": "source",
    "benative_answer_pattern": "concept",
    "timeline_month": "source",
    # Common typo from planning notes; keep as an alias, write the canonical form.
    "comparsion": "comparison",
}


def normalize_page_type(page_type: str) -> str:
    """Return the canonical wiki page type for new writes."""
    canonical = LEGACY_PAGE_TYPE_MAP.get(page_type, page_type)
    if canonical not in ALLOWED_PAGE_TYPES:
        raise ValueError(
            f"Unknown page type '{page_type}'. Allowed: {sorted(ALLOWED_PAGE_TYPES)}"
        )
    return canonical

# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9/_-]*$")


def _validate_slug(slug: str) -> str:
    # Check for leading '/' first (produces clearer error)
    if slug.startswith("/"):
        raise ValueError(f"Slug '{slug}' must not start with '/'")
    # Check `..` next — regex cannot block it (e.g. `abc/..` matches the pattern)
    if ".." in slug:
        raise ValueError(f"Slug '{slug}' must not contain '..'")
    if not _SLUG_RE.match(slug):
        raise ValueError(
            f"Invalid slug '{slug}': must match ^[a-z0-9][a-z0-9/_-]*$"
        )
    return slug


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class WikiSource(BaseModel):
    """A single source reference for a piece of knowledge."""

    kind: str = Field(..., description="Source kind: session, file, manual, etc.")
    session_id: str | None = Field(default=None, description="Session UUID if applicable")
    message_id: str | None = Field(default=None, description="Message ID within session")
    file: str | None = Field(default=None, description="File path if from file")
    timestamp: str | None = Field(default=None, description="ISO timestamp")


class WikiSourcesEntry(BaseModel):
    """One fact entry in the sidecar sources.json."""

    text: str = Field(..., description="Original fact text as stored in Markdown")
    section: str = Field(..., description="Section this fact belongs to")
    sources: list[WikiSource] = Field(default_factory=list)
    confirmations: int = Field(default=1, ge=1)
    first_seen: str = Field(...)
    last_seen: str = Field(...)


class WikiSourcesData(BaseModel):
    """The sidecar sources.json file format."""

    facts: dict[str, WikiSourcesEntry] = Field(default_factory=dict)


class WikiPatch(BaseModel):
    """A patch to apply to a wiki page."""

    operation: Literal[
        "create_page",
        "merge_section",
        "append_section",
        "replace_section",
        "add_link",
        "deprecate_fact",
        "update_summary",
    ]
    slug: str = Field(...)
    title: str = Field(...)
    type: str = Field(...)
    mode: Literal["global", "ielts", "freechat", "benative", "language"]
    section: str | None = Field(default=None)
    content: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    sources: list[WikiSource] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = Field(default="medium")
    reason: str | None = Field(default=None)

    _slug_validated: bool = False

    @field_validator("slug")
    @classmethod
    def check_slug(cls, v: str) -> str:
        return _validate_slug(v)

    @field_validator("type")
    @classmethod
    def check_type(cls, v: str) -> str:
        return normalize_page_type(v)

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in ALLOWED_MODES:
            raise ValueError(f"Unknown mode '{v}'. Allowed: {sorted(ALLOWED_MODES)}")
        return v

    @model_validator(mode="after")
    def check_write_has_sources(self) -> "WikiPatch":
        """Write operations must include at least one source."""
        if self.operation in ALLOWED_OPERATIONS - {"add_link", "deprecate_fact"}:
            if not self.sources:
                raise ValueError(
                    f"Patch operation '{self.operation}' requires at least one source"
                )
        return self

    def normalized_fact_key(self, fact_text: str) -> str:
        """Return a normalized key for fact deduplication.

        Normalization: lowercase + strip leading/trailing punctuation.
        """
        import re
        normalized = fact_text.lower().strip()
        normalized = re.sub(r"^[^\w]+|[^\w]+$", "", normalized)
        return normalized


class WikiPageMeta(BaseModel):
    """Frontmatter metadata for a wiki page."""

    slug: str = Field(...)
    title: str = Field(...)
    type: str = Field(...)
    mode: Literal["global", "ielts", "freechat", "benative", "language"]
    status: Literal["draft", "active", "review", "deprecated", "archived"] = Field(
        default="active"
    )
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    created_at: str = Field(default="")
    updated_at: str = Field(...)
    last_reviewed_at: str | None = Field(default=None)
    confidence: Literal["low", "medium", "high"] = Field(default="medium")
    stability: Literal["volatile", "stable", "canonical"] = Field(default="volatile")
    version: int = Field(default=1, ge=1)

    @field_validator("slug")
    @classmethod
    def check_slug(cls, v: str) -> str:
        return _validate_slug(v)

    @field_validator("type")
    @classmethod
    def check_type(cls, v: str) -> str:
        return normalize_page_type(v)

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in ALLOWED_MODES:
            raise ValueError(f"Unknown mode '{v}'")
        return v


class WikiSearchResult(BaseModel):
    """A single search result from the wiki index."""

    slug: str
    title: str
    type: str
    mode: str
    section: str
    snippet: str
    score: float
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
