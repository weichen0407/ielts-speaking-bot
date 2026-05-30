"""Tests for WikiProcessor."""

from pathlib import Path

import pytest

from subagent.cross_session.wiki.processor.schema import WikiPatch, WikiSource
from subagent.cross_session.wiki.processor.wiki_index import WikiIndex
from subagent.cross_session.wiki.processor.wiki_processor import WikiProcessor


class TestWikiProcessor:
    @pytest.fixture
    def wiki_root(self, tmp_path: Path) -> Path:
        root = tmp_path / "persona" / "wiki"
        root.mkdir(parents=True)
        return root

    @pytest.fixture
    def processor(self, wiki_root: Path) -> WikiProcessor:
        return WikiProcessor(wiki_root=wiki_root)

    def test_process_valid_jsonl(self, wiki_root: Path, processor: WikiProcessor):
        jsonl = (
            '{"operation":"create_page","slug":"test/page","title":"Test","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
            '{"operation":"add_link","slug":"test/page","title":"Test","type":"ielts_topic","mode":"ielts",'
            '"links":["extra/link"],"sources":[{"kind":"manual"}]}\n'
        )
        applied = processor.process_jsonl(jsonl)
        assert len(applied) == 2
        assert applied[0].operation == "create_page"
        assert applied[1].operation == "add_link"

        # Verify page was created with correct links
        page = processor.store.read_page("test/page")
        assert page is not None
        meta, _ = page
        assert "extra/link" in meta.links

    def test_process_none_sentinel(self, wiki_root: Path, processor: WikiProcessor):
        jsonl = "(none)\n"
        applied = processor.process_jsonl(jsonl)
        assert applied == []

    def test_process_invalid_json_skipped(self, wiki_root: Path, processor: WikiProcessor):
        jsonl = (
            '{"operation":"create_page","slug":"test/ok","title":"OK","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
            'not valid json\n'
            '{"operation":"create_page","slug":"test/also_ok","title":"Also OK","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:2"}]}\n'
        )
        applied = processor.process_jsonl(jsonl)
        assert len(applied) == 2

    def test_process_invalid_patch_skipped(self, wiki_root: Path, processor: WikiProcessor):
        jsonl = (
            '{"operation":"create_page","slug":"test/valid","title":"Valid","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
            '{"operation":"create_page","slug":"test/bad_slug","title":"Bad","type":"unknown_type","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:2"}]}\n'
        )
        applied = processor.process_jsonl(jsonl)
        assert len(applied) == 1
        assert applied[0].slug == "test/valid"

    def test_process_empty_lines_skipped(self, wiki_root: Path, processor: WikiProcessor):
        jsonl = (
            '{"operation":"create_page","slug":"test/a","title":"A","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
            '\n'
            '  \n'
            '{"operation":"create_page","slug":"test/b","title":"B","type":"ielts_topic","mode":"ielts",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:2"}]}\n'
        )
        applied = processor.process_jsonl(jsonl)
        assert len(applied) == 2

    def test_process_indexes_pages(self, wiki_root: Path, processor: WikiProcessor):
        jsonl = (
            '{"operation":"create_page","slug":"test/indexed","title":"Indexed","type":"ielts_topic","mode":"ielts",'
            '"section":"User Material","content":"Content here.",'
            '"sources":[{"kind":"session","session_id":"x","message_id":"u:1"}]}\n'
        )
        processor.process_jsonl(jsonl)

        # Verify index was updated
        conn = processor.index._conn()
        try:
            cur = conn.execute("SELECT slug FROM pages WHERE slug = 'test/indexed'")
            row = cur.fetchone()
            assert row is not None
        finally:
            conn.close()

    def test_process_rejected_patch_not_indexed(self, wiki_root: Path, processor: WikiProcessor):
        jsonl = (
            '{"operation":"merge_section","slug":"test/rejected","title":"Rejected","type":"ielts_topic","mode":"ielts",'
            '"section":"User Material","content":"No sources here.","sources":[]}\n'
        )
        applied = processor.process_jsonl(jsonl)
        assert applied == []
