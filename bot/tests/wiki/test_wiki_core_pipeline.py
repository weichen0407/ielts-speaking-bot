"""Tests for the new wiki ingest/query/crystallize/lint core."""

import json
from pathlib import Path

from subagent.cross_session.wiki.processor.wiki_crystallizer import WikiCrystallizer
from subagent.cross_session.wiki.processor.wiki_ingest import WikiIngestor
from subagent.cross_session.wiki.processor.wiki_lint import WikiLinter
from subagent.cross_session.wiki.processor.wiki_query import WikiQueryEngine
from subagent.cross_session.wiki.processor.wiki_store import WikiStore


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
    assert result.queued
    queued_lines = (wiki_root / "state" / "queue.jsonl").read_text(encoding="utf-8").splitlines()
    queued = [json.loads(line) for line in queued_lines]
    assert queued[0]["patch"]["memory_status"] == "needs_user_confirmation"

    results = WikiQueryEngine(wiki_root=wiki_root).query("wiki schema", limit=5)
    assert results
    assert all(result.type in {"source", "decision", "question", "synthesis"} for result in results)

    findings = WikiLinter(wiki_root=wiki_root).lint()
    assert not [finding for finding in findings if finding.severity == "error"]
    source_page = next(page for page in WikiStore(workspace=workspace, wiki_root=wiki_root).list_pages() if page.type == "source")
    assert source_page.memory_status == "confirmed"


def test_ingest_filters_operational_noise(tmp_path: Path):
    workspace = tmp_path
    data_dir = workspace / "persona" / "events"
    data_dir.mkdir(parents=True)
    thread_path = data_dir / "thread.jsonl"
    events = [
        {
            "id": "noise-command",
            "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 1},
            "role": "user",
            "content": {"type": "text", "text": "/mode benative"},
        },
        {
            "id": "noise-test",
            "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 2},
            "role": "user",
            "content": {"type": "text", "text": "test"},
        },
        {
            "id": "noise-error",
            "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 3},
            "role": "user",
            "content": {"type": "text", "text": "Error: duplicate tool_call_id"},
        },
        {
            "id": "real-signal",
            "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 4},
            "role": "user",
            "content": {
                "type": "text",
                "text": "I like basketball, traveling to Paris, and watching Arsenal.",
            },
        },
    ]
    thread_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )

    ingestor = WikiIngestor(workspace=workspace, wiki_root=workspace / "persona" / "wiki")
    batch = ingestor.ingest_thread_delta(
        session_id="s1",
        allowed_modes={"freechat"},
        allowed_roles={"user"},
    )
    analysis = ingestor.analyze(batch)

    assert [message.event_id for message in batch.messages] == ["real-signal"]
    assert analysis.candidates
    assert "Paris" in analysis.candidates[0].content


def test_real_freechat_signals_crystallize_without_schema_projection(tmp_path: Path):
    workspace = tmp_path
    data_dir = workspace / "persona" / "events"
    data_dir.mkdir(parents=True)
    thread_path = data_dir / "thread.jsonl"
    events = [
        {
            "id": "sports-travel",
            "timestamp": "2026-05-30T10:00:00+08:00",
            "source": {"mode": "freechat", "session_uuid": "s1", "message_index": 1},
            "role": "user",
            "content": {
                "type": "text",
                "text": "I like basketball, traveling to Paris, watching Arsenal, and improving IELTS speaking fluency.",
            },
        }
    ]
    thread_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )

    wiki_root = workspace / "persona" / "wiki"
    ingestor = WikiIngestor(workspace=workspace, wiki_root=wiki_root)
    batch = ingestor.ingest_thread_delta(
        session_id="s1",
        allowed_modes={"freechat"},
        allowed_roles={"user"},
    )
    analysis = ingestor.analyze(batch)
    result = WikiCrystallizer(wiki_root=wiki_root).save_analysis(analysis, mode="freechat")

    assert result.applied
    results = WikiQueryEngine(wiki_root=wiki_root).query("Paris Arsenal basketball", limit=5)
    assert results
    joined = "\n".join(result.snippet for result in results)
    assert "Paris" in joined
    assert "Arsenal" in joined

    findings = WikiLinter(wiki_root=wiki_root).lint()
    assert not [
        finding for finding in findings
        if finding.severity == "error" or finding.code == "schema_projection_noise"
    ]
