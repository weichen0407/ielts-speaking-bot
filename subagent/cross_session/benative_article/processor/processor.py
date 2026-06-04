"""BenativeArticleProcessor - prepares article pairs and entities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from subagent._shared.base import BaseDataProcessor
from subagent._shared.benative_schema import ArticleEntity, ArticleRecord, SentencePair
from subagent._shared.utils import ensure_output_dir, parse_tab_line, split_batch_items

from .schema import BenativeArticleInput, BenativeArticleOutput


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_ints(value: str | None) -> list[int]:
    indexes: list[int] = []
    for item in _split_csv(value):
        try:
            indexes.append(int(item))
        except ValueError:
            continue
    return indexes


def _workspace_from_output(output_path: Path) -> Path:
    for parent in [output_path, *output_path.parents]:
        if parent.name == "persona":
            return parent.parent
    return output_path.parent.parent.parent


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text.strip()
    try:
        _, raw_meta, body = text.split("---", 2)
    except ValueError:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"')
    return meta, body.strip()


class BenativeArticleProcessor(BaseDataProcessor[BenativeArticleInput, BenativeArticleOutput]):
    """Prepare article metadata, Chinese pairs, and entity hints."""

    name = "benative_article"

    def get_input_schema(self) -> type[BenativeArticleInput]:
        return BenativeArticleInput

    def get_output_schema(self) -> type[BenativeArticleOutput]:
        return BenativeArticleOutput

    def read(self, path: Path) -> list[dict[str, Any]]:
        if path.suffix.lower() == ".md":
            meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
            article_id = meta.get("id") or path.stem
            return [{
                "article_id": article_id,
                "title": meta.get("title") or path.stem.replace("-", " ").title(),
                "topic": meta.get("topic"),
                "level": meta.get("level"),
                "source_type": meta.get("source_type") or "fixed",
                "source_url": meta.get("source_url"),
                "content": body,
            }]

        rows = super().read(path)
        base_dir = path.parent
        for row in rows:
            source_path = row.get("path") or row.get("source_path")
            if source_path and not row.get("content"):
                candidate = Path(str(source_path))
                if not candidate.is_absolute():
                    candidate = (base_dir / candidate).resolve()
                if candidate.exists() and candidate.is_file():
                    if candidate.suffix.lower() == ".md":
                        meta, body = _parse_frontmatter(candidate.read_text(encoding="utf-8"))
                        row.setdefault("article_id", meta.get("id") or candidate.stem)
                        row.setdefault("title", meta.get("title") or candidate.stem.replace("-", " ").title())
                        row.setdefault("topic", meta.get("topic"))
                        row.setdefault("level", meta.get("level"))
                        row.setdefault("source_type", meta.get("source_type") or "fixed")
                        row.setdefault("source_url", meta.get("source_url"))
                        row["content"] = body
                    else:
                        row["content"] = candidate.read_text(encoding="utf-8")
        return rows

    def get_system_prompt(self) -> str:
        return r"""You are the benative_article subagent.
Prepare English article material for Be Native reconstruction practice.

Return only tab-separated rows. Do not write files. The processor will validate and persist artifacts.

Output formats:
ARTICLE	article_id	title	topic	level	summary
PAIR	article_id	sentence_index	paragraph_index	en	zh
ENTITY	article_id	surface	type	canonical	zh	aliases	source_sentence_indexes

Rules:
- Split the English article into clear sentence-level practice units.
- Translate each English sentence into natural Chinese.
- Preserve sentence_index starting from 0.
- Extract useful entities, proper nouns, key terms, and topic keywords.
- Entity type should be one of: person, organization, location, product, event, topic_keyword, proper_noun, term, other.
- aliases are comma-separated.
- source_sentence_indexes are comma-separated integers.

If there is no usable article content, output (none)."""

    def build_user_prompt(self, data: list[BenativeArticleInput]) -> str:
        lines: list[str] = []
        for item in data:
            lines.append(f"ARTICLE_ID: {item.article_id}")
            lines.append(f"TITLE: {item.title}")
            if item.topic:
                lines.append(f"TOPIC: {item.topic}")
            if item.level:
                lines.append(f"LEVEL: {item.level}")
            lines.append("CONTENT:")
            lines.append(item.content)
            lines.append("---")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[BenativeArticleOutput]:
        results: list[BenativeArticleOutput] = []
        for item in split_batch_items(raw_output):
            for line in item.splitlines():
                line = line.strip()
                if not line or line == "(none)":
                    continue
                kind = line.split("\t", 1)[0].strip().upper()
                if kind == "ARTICLE":
                    parsed = parse_tab_line(line, 6, min_fields=3)
                    if not parsed:
                        continue
                    _, article_id, title, *rest = parsed
                    topic = rest[0] if len(rest) > 0 else None
                    level = rest[1] if len(rest) > 1 else None
                    summary = rest[2] if len(rest) > 2 else None
                    results.append(BenativeArticleOutput(
                        record_type="article",
                        article_id=article_id,
                        title=title,
                        topic=topic or None,
                        level=level or None,
                        summary=summary or None,
                    ))
                elif kind == "PAIR":
                    parsed = parse_tab_line(line, 6)
                    if not parsed:
                        continue
                    _, article_id, sentence_index, paragraph_index, en, zh = parsed
                    try:
                        sent_idx = int(sentence_index)
                        para_idx = int(paragraph_index)
                    except ValueError:
                        continue
                    results.append(BenativeArticleOutput(
                        record_type="pair",
                        article_id=article_id,
                        sentence_index=sent_idx,
                        paragraph_index=para_idx,
                        en=en,
                        zh=zh,
                    ))
                elif kind == "ENTITY":
                    parsed = parse_tab_line(line, 8, min_fields=4)
                    if not parsed:
                        continue
                    _, article_id, surface, entity_type, *rest = parsed
                    canonical = rest[0] if len(rest) > 0 else None
                    zh = rest[1] if len(rest) > 1 else None
                    aliases = rest[2] if len(rest) > 2 else None
                    indexes = rest[3] if len(rest) > 3 else None
                    results.append(BenativeArticleOutput(
                        record_type="entity",
                        article_id=article_id,
                        surface=surface,
                        type=entity_type,
                        canonical=canonical or None,
                        zh=zh or None,
                        aliases=_split_csv(aliases),
                        source_sentence_indexes=_split_ints(indexes),
                    ))
        return results

    def serialize(self, data: list[BenativeArticleOutput], output_path: Path, format: str = "both"):
        super().serialize(data, output_path, format)
        workspace = _workspace_from_output(output_path)
        benative_root = workspace / "persona" / "benative"

        articles: dict[str, ArticleRecord] = {}
        pairs: dict[str, list[SentencePair]] = {}
        entities: dict[str, list[ArticleEntity]] = {}

        for item in data:
            if item.record_type == "article":
                articles[item.article_id] = ArticleRecord(
                    article_id=item.article_id,
                    title=item.title or item.article_id,
                    topic=item.topic,
                    level=item.level,
                    summary=item.summary,
                )
            elif item.record_type == "pair" and item.en and item.zh and item.sentence_index is not None:
                pairs.setdefault(item.article_id, []).append(SentencePair(
                    article_id=item.article_id,
                    sentence_index=item.sentence_index,
                    paragraph_index=item.paragraph_index or 0,
                    en=item.en,
                    zh=item.zh,
                ))
            elif item.record_type == "entity" and item.surface:
                entities.setdefault(item.article_id, []).append(ArticleEntity(
                    article_id=item.article_id,
                    surface=item.surface,
                    type=item.type or "other",
                    canonical=item.canonical,
                    zh=item.zh,
                    aliases=item.aliases,
                    source_sentence_indexes=item.source_sentence_indexes,
                ))

        for article_id, article in articles.items():
            path = benative_root / "articles" / f"{article_id}.json"
            ensure_output_dir(path)
            path.write_text(article.model_dump_json(indent=2) + "\n", encoding="utf-8")

        for article_id, rows in pairs.items():
            path = benative_root / "pairs" / f"{article_id}.jsonl"
            ensure_output_dir(path)
            with path.open("a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(row.model_dump_json() + "\n")

        for article_id, rows in entities.items():
            path = benative_root / "entities" / f"{article_id}.jsonl"
            ensure_output_dir(path)
            with path.open("a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(row.model_dump_json() + "\n")

    def to_md(self, parsed_data: list[BenativeArticleOutput]) -> str:
        if not parsed_data:
            return "# Be Native Article\n\n(none)\n"
        lines = ["# Be Native Article", ""]
        for item in parsed_data:
            if item.record_type == "article":
                lines.append(f"## Article: {item.title or item.article_id}")
                if item.summary:
                    lines.append(item.summary)
                lines.append("")
            elif item.record_type == "pair":
                lines.append(f"- [{item.article_id}:{item.sentence_index}] {item.en} -> {item.zh}")
            elif item.record_type == "entity":
                lines.append(f"- Entity: {item.surface} ({item.type or 'other'})")
        return "\n".join(lines) + "\n"
