"""Schemas for the Be Native article processor."""

from __future__ import annotations

from pydantic import BaseModel, Field

from subagent._shared.benative_schema import ArticleSource


class BenativeArticleInput(ArticleSource):
    """Processor input for fixed or downloaded article material."""


class BenativeArticleOutput(BaseModel):
    """Unified output row for article metadata, sentence pairs, and entities.

    LLM output format:
    ARTICLE	article_id	title	topic	level	summary
    PAIR	article_id	sentence_index	paragraph_index	en	zh
    ENTITY	article_id	surface	type	canonical	zh	aliases	source_sentence_indexes
    """

    record_type: str
    article_id: str
    title: str | None = None
    topic: str | None = None
    level: str | None = None
    summary: str | None = None
    sentence_index: int | None = None
    paragraph_index: int | None = None
    en: str | None = None
    zh: str | None = None
    surface: str | None = None
    type: str | None = None
    canonical: str | None = None
    aliases: list[str] = Field(default_factory=list)
    source_sentence_indexes: list[int] = Field(default_factory=list)
