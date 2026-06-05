"""Wiki sync - ingest thread deltas into the LLM wiki core pipeline."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.capabilities import wiki_sync_allowed_modes


async def sync_session_to_wiki(
    session_key: str,
    session_dir: str,
    workspace: Path,
    provider: Any | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Sync latest session messages to wiki through ingest/query/save/lint.

    Returns a structured run record. The core pipeline remains local and
    deterministic by default. Set NANOBOT_WIKI_LLM_EXTRACTOR=1 to add the
    taxonomy-guided LLM extractor before crystallization.
    """

    workspace = Path(workspace)
    _ensure_repo_importable(workspace)

    from subagent.cross_session.wiki.processor.wiki_crystallizer import WikiCrystallizer
    from subagent.cross_session.wiki.processor.wiki_ingest import WikiIngestAnalysis, WikiIngestor
    from subagent.cross_session.wiki.processor.wiki_lint import WikiLinter
    from subagent.cross_session.wiki.processor.wiki_layout import ensure_wiki_layout
    from subagent.cross_session.wiki.processor.wiki_llm_extractor import WikiLLMExtractor
    from subagent.cross_session.wiki.processor.wiki_taxonomy import WikiTaxonomy, default_taxonomy_path
    from subagent.cross_session.wiki.processor.wiki_topic_review import TopicReviewQueue

    wiki_root = workspace / "persona" / "wiki"
    layout = ensure_wiki_layout(wiki_root)
    started_at = datetime.now().isoformat()
    record: dict[str, Any] = {
        "timestamp": started_at,
        "session_id": session_key,
        "status": "started",
        "messages": 0,
        "candidates": 0,
        "patches": 0,
        "applied": 0,
        "lint_findings": 0,
        "llm_extractor_enabled": False,
        "llm_candidates": 0,
        "topic_review_items": 0,
        "allowed_modes": sorted(wiki_sync_allowed_modes(workspace)),
    }

    try:
        ingestor = WikiIngestor(workspace=workspace, wiki_root=wiki_root)
        batch = ingestor.ingest_thread_delta(
            session_id=session_key,
            limit=40,
            advance_cursor=True,
            allowed_modes=wiki_sync_allowed_modes(workspace),
        )
        analysis = ingestor.analyze(batch)
        if _should_run_llm_extractor(provider, batch.messages):
            record["llm_extractor_enabled"] = True
            try:
                taxonomy = WikiTaxonomy.load(default_taxonomy_path(workspace))
                extraction = await WikiLLMExtractor(
                    provider=provider,
                    model=model,
                    taxonomy=taxonomy,
                ).extract(batch)
                review_queue = TopicReviewQueue(layout.state_root / "topic_review_queue.jsonl")
                for item in extraction.topic_review_items:
                    review_queue.upsert(item)
                candidates = _merge_candidates(analysis.candidates, extraction.candidates)
                analysis = WikiIngestAnalysis(batch=batch, candidates=candidates)
                record["llm_candidates"] = len(extraction.candidates)
                record["topic_review_items"] = len(extraction.topic_review_items)
                record["llm_invalid_lines"] = extraction.invalid_lines
            except Exception as e:
                record["llm_extractor_error"] = str(e)
                logger.warning("Wiki LLM extractor failed for session {}: {}", session_key, e)
        result = WikiCrystallizer(wiki_root=wiki_root).save_analysis(
            analysis,
            mode=_mode_from_session(workspace, session_key, session_dir),
        )
        findings = WikiLinter(wiki_root=wiki_root).lint()

        record.update(
            {
                "status": "ok",
                "source_id": batch.source_id,
                "source_file": str(batch.source_file.relative_to(wiki_root))
                if batch.source_file.exists()
                else "",
                "messages": len(batch.messages),
                "candidates": len(analysis.candidates),
                "patches": len(result.patches),
                "applied": len(result.applied),
                "applied_slugs": [patch.slug for patch in result.applied],
                "lint_findings": len(findings),
                "lint_errors": len([f for f in findings if f.severity == "error"]),
            }
        )
        logger.info(
            "Wiki sync: session={} messages={} candidates={} applied={} lint={}",
            session_key,
            record["messages"],
            record["candidates"],
            record["applied"],
            record["lint_findings"],
        )
    except Exception as e:
        record.update({"status": "error", "error": str(e)})
        logger.warning("Wiki sync failed for session {}: {}", session_key, e)

    _append_sync_log(layout.state_root / "sync_log.jsonl", record)
    return record


def _ensure_repo_importable(workspace: Path) -> None:
    repo_root = workspace if (workspace / "subagent").exists() else Path(__file__).resolve().parents[3]
    repo = str(repo_root)
    if repo not in sys.path:
        sys.path.insert(0, repo)


def _append_sync_log(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _should_run_llm_extractor(provider: Any | None, messages: list[Any]) -> bool:
    flag = os.environ.get("NANOBOT_WIKI_LLM_EXTRACTOR", "").strip().lower()
    enabled = flag in {"1", "true", "yes", "on"}
    return bool(enabled and provider is not None and messages)


def _merge_candidates(*groups):
    seen: set[tuple[str, str]] = set()
    merged = []
    for group in groups:
        for candidate in group:
            key = (candidate.type, candidate.content.lower().strip())
            if key in seen:
                continue
            seen.add(key)
            merged.append(candidate)
    return merged


def _mode_from_session(workspace: Path, session_key: str, session_dir: str | None) -> str:
    thread_path = (
        Path(session_dir) / "thread.jsonl"
        if session_dir
        else workspace / "persona" / "sessions" / session_key / "thread.jsonl"
    )
    if not thread_path.exists():
        thread_path = workspace / "persona" / "sessions" / session_key / "thread.jsonl"
    if not thread_path.exists():
        return "global"
    try:
        with thread_path.open("r", encoding="utf-8") as fh:
            first = fh.readline()
        data = json.loads(first) if first.strip() else {}
    except json.JSONDecodeError:
        return "global"
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    mode = metadata.get("mode")
    return mode if mode in {"global", "ielts", "freechat", "benative", "language"} else "global"
