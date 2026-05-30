"""Tests for WikiUpdater."""

import json
from pathlib import Path

import pytest

from subagent.cross_session.wiki.processor.schema import WikiPatch, WikiSource
from subagent.cross_session.wiki.processor.wiki_index import WikiIndex
from subagent.cross_session.wiki.processor.wiki_updater import WikiUpdater


class TestWikiUpdater:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    @pytest.fixture
    def updater(self, wiki_root: Path, tmp_path: Path) -> WikiUpdater:
        cursor_path = tmp_path / "cursors.json"
        return WikiUpdater(wiki_root=wiki_root, cursor_path=cursor_path)

    @pytest.fixture
    def source_file(self, tmp_path: Path) -> Path:
        return tmp_path / "source.jsonl"

    def test_first_run_processes_all_lines(self, wiki_root: Path, updater: WikiUpdater, source_file: Path):
        source_file.write_text(
            '{"operation":"create_page","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
            '{"operation":"create_page","slug":"test/b","title":"B","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:2"}]}\n'
        )
        applied = updater.scan_source(source_file)
        assert len(applied) == 2
        assert updater.get_cursor(source_file) == 2

    def test_second_run_processes_no_lines(self, wiki_root: Path, updater: WikiUpdater, source_file: Path):
        source_file.write_text(
            '{"operation":"create_page","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
        )
        updater.scan_source(source_file)
        applied = updater.scan_source(source_file)
        assert applied == []

    def test_cursor_advances_after_each_patch(self, wiki_root: Path, updater: WikiUpdater, source_file: Path):
        source_file.write_text(
            '{"operation":"create_page","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
            '{"operation":"create_page","slug":"test/b","title":"B","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:2"}]}\n'
        )
        updater.scan_source(source_file)
        assert updater.get_cursor(source_file) == 2

    def test_cursor_not_advanced_on_rejection(self, wiki_root: Path, updater: WikiUpdater, source_file: Path):
        # merge_section without sources should be rejected
        source_file.write_text(
            '{"operation":"create_page","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
            '{"operation":"merge_section","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"section":"User Material","content":"Content","sources":[]}\n'
        )
        applied = updater.scan_source(source_file)
        # First patch applied, second rejected
        assert len(applied) == 1
        # Cursor should stop at the rejected line
        assert updater.get_cursor(source_file) == 1

    def test_none_sentinel_skipped(self, wiki_root: Path, updater: WikiUpdater, source_file: Path):
        source_file.write_text(
            '"(none)"\n'
            '{"operation":"create_page","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
        )
        applied = updater.scan_source(source_file)
        assert len(applied) == 1
        assert updater.get_cursor(source_file) == 2

    def test_reset_cursor(self, wiki_root: Path, updater: WikiUpdater, source_file: Path):
        source_file.write_text(
            '{"operation":"create_page","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
        )
        updater.scan_source(source_file)
        assert updater.get_cursor(source_file) == 1

        updater.reset_cursor(source_file)
        assert updater.get_cursor(source_file) == 0

        # Next scan should process again
        applied = updater.scan_source(source_file)
        assert len(applied) == 1

    def test_missing_source_file_skipped(self, wiki_root: Path, updater: WikiUpdater):
        missing = Path("/nonexistent/source.jsonl")
        applied = updater.scan_source(missing)
        assert applied == []

    def test_cursors_persisted(self, wiki_root: Path, tmp_path: Path, source_file: Path):
        cursor_path = tmp_path / "cursors.json"
        updater = WikiUpdater(wiki_root=wiki_root, cursor_path=cursor_path)

        source_file.write_text(
            '{"operation":"create_page","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
        )
        updater.scan_source(source_file)
        updater.save()

        # New updater instance should pick up cursor
        updater2 = WikiUpdater(wiki_root=wiki_root, cursor_path=cursor_path)
        assert updater2.get_cursor(source_file) == 1

    def test_scan_all_multiple_sources(self, wiki_root: Path, tmp_path: Path):
        cursor_path = tmp_path / "cursors.json"
        updater = WikiUpdater(wiki_root=wiki_root, cursor_path=cursor_path)

        src1 = tmp_path / "src1.jsonl"
        src2 = tmp_path / "src2.jsonl"

        src1.write_text(
            '{"operation":"create_page","slug":"test/src1","title":"Src1","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
        )
        src2.write_text(
            '{"operation":"create_page","slug":"test/src2","title":"Src2","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:2"}]}\n'
        )

        applied = updater.scan_all(sources=[src1, src2])
        assert len(applied) == 2
        assert {p.slug for p in applied} == {"test/src1", "test/src2"}
