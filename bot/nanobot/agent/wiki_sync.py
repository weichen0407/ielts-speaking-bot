"""Wiki sync - ingest thread deltas into the LLM wiki core pipeline."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


async def sync_session_to_wiki(
    session_key: str,
    session_dir: str,
    workspace: Path,
    provider: Any | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Sync latest session messages to wiki through ingest/query/save/lint.

    Returns a structured run record. The provider/model parameters are kept
    for compatibility with the old LLM-based sync entrypoint; the current core
    pipeline is local and deterministic.
    """

    del session_dir, provider, model

    workspace = Path(workspace)
    _ensure_repo_importable(workspace)

    from subagent.cross_session.wiki.processor.wiki_crystallizer import WikiCrystallizer
    from subagent.cross_session.wiki.processor.wiki_ingest import WikiIngestor
    from subagent.cross_session.wiki.processor.wiki_lint import WikiLinter
    from subagent.cross_session.wiki.processor.wiki_layout import ensure_wiki_layout

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
    }

    try:
        ingestor = WikiIngestor(workspace=workspace, wiki_root=wiki_root)
        batch = ingestor.ingest_thread_delta(
            session_id=session_key,
            limit=40,
            advance_cursor=True,
        )
        analysis = ingestor.analyze(batch)
        result = WikiCrystallizer(wiki_root=wiki_root).save_analysis(
            analysis,
            mode=_mode_from_session_dir(workspace, session_key),
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


def _mode_from_session_dir(workspace: Path, session_key: str) -> str:
    metadata_path = workspace / "persona" / "sessions" / session_key / "metadata.json"
    if not metadata_path.exists():
        return "global"
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "global"
    mode = data.get("mode")
    return mode if mode in {"global", "ielts", "freechat", "benative", "language"} else "global"
