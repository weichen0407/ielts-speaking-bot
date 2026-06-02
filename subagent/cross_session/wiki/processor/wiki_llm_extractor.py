"""Taxonomy-guided LLM extractor for wiki candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .wiki_ingest import IngestMessage, WikiCandidate, WikiIngestBatch
from .wiki_taxonomy import WikiTaxonomy
from .wiki_topic_review import TopicReviewItem


class ExtractedRelation(BaseModel):
    subject: str
    predicate: str
    object: str


class CandidateNewTopic(BaseModel):
    suggested_domain: str
    suggested_topic: str
    reason: str = ""


class ExtractedWikiCandidate(BaseModel):
    domain: str
    topic: str
    subtype: str
    wiki_type: Literal[
        "entity",
        "concept",
        "comparison",
        "question",
        "synthesis",
        "decision",
        "gap",
        "meta",
    ]
    title: str
    content: str
    entities: list[str] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"
    candidate_new_topic: CandidateNewTopic | None = None

    @field_validator("source_refs")
    @classmethod
    def require_source_refs(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("source_refs is required")
        return value


@dataclass
class WikiLLMExtractionResult:
    candidates: list[WikiCandidate] = field(default_factory=list)
    topic_review_items: list[TopicReviewItem] = field(default_factory=list)
    invalid_lines: int = 0
    raw_output: str = ""


class WikiLLMExtractor:
    """Extract taxonomy-guided WikiCandidate objects from raw thread messages."""

    def __init__(self, *, provider: Any, model: str | None, taxonomy: WikiTaxonomy):
        self.provider = provider
        self.model = model
        self.taxonomy = taxonomy

    async def extract(self, batch: WikiIngestBatch) -> WikiLLMExtractionResult:
        if not batch.messages:
            return WikiLLMExtractionResult()

        raw_output = await self._call_llm(batch.messages)
        return self.parse_output(raw_output, batch.messages)

    def parse_output(
        self,
        raw_output: str,
        messages: list[IngestMessage],
    ) -> WikiLLMExtractionResult:
        result = WikiLLMExtractionResult(raw_output=raw_output)
        message_by_ref = {message.source_ref: message for message in messages}

        for line in raw_output.splitlines():
            line = line.strip()
            if not line or line == "(none)":
                continue
            try:
                data = json.loads(line)
                extracted = ExtractedWikiCandidate(**data)
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
                result.invalid_lines += 1
                continue

            domain, topic, subtype = self.taxonomy.normalize(
                extracted.domain,
                extracted.topic,
                extracted.subtype,
            )
            is_fallback = (
                domain == self.taxonomy.fallback.domain
                and topic == self.taxonomy.fallback.topic
                and subtype == self.taxonomy.fallback.subtype
            )

            tags = [
                f"domain:{domain}",
                f"topic:{topic}",
                f"subtype:{subtype}",
                "llm-extracted",
            ]
            tags.extend(f"entity:{entity}" for entity in extracted.entities[:8])
            relation_lines = [
                f"- {rel.subject} {rel.predicate} {rel.object}"
                for rel in extracted.relations[:8]
            ]
            content = extracted.content.strip()
            if relation_lines:
                content = f"{content}\n\nRelations:\n" + "\n".join(relation_lines)

            result.candidates.append(
                WikiCandidate(
                    type=extracted.wiki_type,
                    title=extracted.title,
                    content=content,
                    source_refs=extracted.source_refs,
                    confidence=extracted.confidence,
                    tags=tags,
                    topics=[self.taxonomy.topic_path(domain, topic)],
                )
            )

            if extracted.candidate_new_topic is not None or is_fallback:
                review_data = (
                    extracted.candidate_new_topic.model_dump()
                    if extracted.candidate_new_topic is not None
                    else {
                        "suggested_domain": extracted.domain or "other",
                        "suggested_topic": extracted.topic or "uncategorized",
                        "reason": "Extractor used fallback taxonomy values.",
                    }
                )
                samples = [
                    message_by_ref[ref].text
                    for ref in extracted.source_refs
                    if ref in message_by_ref
                ][:3]
                item = TopicReviewItem.from_candidate(
                    review_data,
                    source_refs=extracted.source_refs,
                    sample_messages=samples,
                )
                if item is not None:
                    result.topic_review_items.append(item)

        return result

    async def _call_llm(self, messages: list[IngestMessage]) -> str:
        prompt_messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._user_prompt(messages)},
        ]
        kwargs = {
            "messages": prompt_messages,
            "tools": None,
            "model": self.model,
            "max_tokens": 2500,
            "temperature": 0.1,
        }
        if hasattr(self.provider, "chat_with_retry"):
            response = await self.provider.chat_with_retry(**kwargs)
        else:
            response = await self.provider.chat(**kwargs)
        finish_reason = getattr(response, "finish_reason", "stop")
        if finish_reason == "error":
            raise RuntimeError(getattr(response, "content", None) or "wiki LLM extractor failed")
        return getattr(response, "content", None) or ""

    def _system_prompt(self) -> str:
        return (
            "You are a taxonomy-guided memory extraction worker for an English learning app.\n"
            "Extract only durable, useful user-memory candidates from the provided messages.\n"
            "Return JSONL only, one JSON object per line. Do not wrap in markdown.\n"
            "Do not invent taxonomy values. Choose domain/topic/subtype exactly from the taxonomy.\n"
            "If nothing fits, use the fallback taxonomy and include candidate_new_topic.\n"
            "Every candidate must include source_refs copied exactly from the input.\n"
            "Prefer concise facts and learning-relevant concepts. Avoid storing throwaway examples.\n\n"
            "Allowed wiki_type values: entity, concept, comparison, question, synthesis, decision, gap, meta.\n\n"
            f"{self.taxonomy.allowed_values_for_prompt()}"
        )

    def _user_prompt(self, messages: list[IngestMessage]) -> str:
        lines = ["Messages:"]
        for message in messages:
            lines.append(
                json.dumps(
                    {
                        "source_ref": message.source_ref,
                        "role": message.role,
                        "text": message.text,
                    },
                    ensure_ascii=False,
                )
            )
        lines.append("")
        lines.append("Output schema:")
        lines.append(
            json.dumps(
                {
                    "domain": "sports",
                    "topic": "football",
                    "subtype": "favorite_team",
                    "wiki_type": "entity",
                    "title": "Arsenal Supporter Profile",
                    "content": "User's favorite football club is Arsenal.",
                    "entities": ["Arsenal"],
                    "relations": [
                        {"subject": "user", "predicate": "supports", "object": "Arsenal"}
                    ],
                    "source_refs": ["thread:session-id:message-id"],
                    "confidence": "high",
                    "candidate_new_topic": None,
                },
                ensure_ascii=False,
            )
        )
        return "\n".join(lines)
