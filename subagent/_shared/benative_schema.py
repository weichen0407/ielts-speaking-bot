"""Shared schemas for Be Native processors and runtime events."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArticleSource(BaseModel):
    """Fixed or downloaded source material to prepare for Be Native."""

    article_id: str
    title: str
    content: str
    topic: str | None = None
    level: str | None = None
    source_type: str = "fixed"
    source_url: str | None = None


class ArticleRecord(BaseModel):
    """Normalized article metadata."""

    article_id: str
    title: str
    topic: str | None = None
    level: str | None = None
    source_type: str = "fixed"
    source_url: str | None = None
    summary: str | None = None


class SentencePair(BaseModel):
    """English/Chinese sentence pair used for reconstruction practice."""

    article_id: str
    sentence_index: int
    paragraph_index: int = 0
    en: str
    zh: str


class ArticleEntity(BaseModel):
    """Entity or term extracted from article material."""

    article_id: str
    surface: str
    type: str = "other"
    canonical: str | None = None
    zh: str | None = None
    aliases: list[str] = Field(default_factory=list)
    source_sentence_indexes: list[int] = Field(default_factory=list)


class BenativeResponse(BaseModel):
    """One user reconstruction answer event."""

    session_uuid: str
    article_id: str
    sentence_index: int
    zh: str
    standard_en: str
    user_en: str
    timestamp: str | None = None


class BenativeReviewItem(BaseModel):
    """Structured feedback comparing user answer with the standard sentence."""

    session_uuid: str
    article_id: str
    sentence_index: int
    accuracy_score: int
    naturalness_score: int
    issue_type: str
    user_en: str
    standard_en: str
    suggested_en: str
    feedback: str
