"""Tests for the new wiki ingest/query/crystallize/lint core."""

import json
from pathlib import Path

from subagent.cross_session.wiki.processor.wiki_crystallizer import WikiCrystallizer
from subagent.cross_session.wiki.processor.wiki_ingest import WikiIngestor
from subagent.cross_session.wiki.processor.wiki_lint import WikiLinter
from subagent.cross_session.wiki.processor.wiki_query import WikiQueryEngine


def test_ingest_crystallize_query_and_lint(tmp_path: Path):
    workspace = tmp_path
    data_dir = workspace / "persona" / "events"
    data_dir.mkdir(parents=True)
    thread_path = data_dir / "thread.jsonl"
    events = [
        {
            "id": "m1",
            "timestamp": "2026-05-30T10:00:00+08:00",
            "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 1},
            "role": "user",
            "content": {"type": "text", "text": "I want to decide the wiki schema first."},
        },
        {
            "id": "m2",
            "timestamp": "2026-05-30T10:01:00+08:00",
            "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 2},
            "role": "user",
            "content": {"type": "text", "text": "What gaps remain in the wiki memory design?"},
        },
    ]
    thread_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )

    wiki_root = workspace / "persona" / "wiki"
    ingestor = WikiIngestor(workspace=workspace, wiki_root=wiki_root)
    batch = ingestor.ingest_thread_delta(session_id="s1")
    analysis = ingestor.analyze(batch)

    assert batch.source_file.exists()
    assert {candidate.type for candidate in analysis.candidates} >= {
        "source",
        "decision",
        "question",
        "gap",
        "synthesis",
    }

    result = WikiCrystallizer(wiki_root=wiki_root).save_analysis(analysis)
    assert result.applied

    results = WikiQueryEngine(wiki_root=wiki_root).query("wiki schema", limit=5)
    assert results
    assert all(result.type in {"source", "decision", "question", "gap", "synthesis"} for result in results)

    findings = WikiLinter(wiki_root=wiki_root).lint()
    assert not [finding for finding in findings if finding.severity == "error"]
