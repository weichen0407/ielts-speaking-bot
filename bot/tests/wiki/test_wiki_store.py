"""Tests for WikiStore."""

import json
import os
from pathlib import Path

import pytest

from subagent.cross_session.wiki.processor.schema import WikiPatch, WikiSource
from subagent.cross_session.wiki.processor.wiki_store import WikiStore, _normalize_bullet, _split_sections


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_patch(**kw) -> WikiPatch:
    defaults = dict(
        operation="merge_section",
        slug="test/page",
        title="Test Page",
        type="ielts_topic",
        mode="ielts",
        section="User Material",
        content="User enjoys basketball.",
        tags=["sports", "hobbies"],
        topics=["sports"],
        links=["user/preferences"],
        sources=[
            WikiSource(
                kind="session",
                session_id="abc",
                message_id="user:1",
                timestamp="2026-05-27T10:00:00+08:00",
            )
        ],
        confidence="medium",
    )
    defaults.update(kw)
    return WikiPatch(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wiki_root(tmp_path: Path) -> Path:
    """A temporary wiki root with persona/wiki/pages structure."""
    root = tmp_path / "persona" / "wiki" / "pages"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def store(wiki_root: Path, tmp_path: Path) -> WikiStore:
    return WikiStore(workspace=tmp_path, wiki_root=wiki_root.parent.parent)


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

class TestPathTraversal:
    def test_page_path_rejects_dotdot(self, store: WikiStore):
        # Slug with ".." is rejected by _validate_slug before path check
        with pytest.raises(ValueError, match="must not contain '..'"):
            store.page_path("../etc/passwd")

    def test_page_path_rejects_absolute(self, store: WikiStore):
        # Absolute-looking slugs fail regex validation (doesn't start with [a-z0-9])
        with pytest.raises(ValueError):
            store.page_path("/etc/passwd")

    def test_sources_path_rejects_dotdot(self, store: WikiStore):
        with pytest.raises(ValueError, match="must not contain '..'"):
            store.sources_path("../etc/passwd")


# ---------------------------------------------------------------------------
# create_page
# ---------------------------------------------------------------------------

class TestCreatePage:
    def test_merge_creates_page(self, store: WikiStore):
        patch = _make_patch(operation="create_page")
        result = store.apply_patch(patch)
        assert result is True
        page = store.read_page("test/page")
        assert page is not None
        meta, body = page
        assert meta.slug == "test/page"
        assert meta.title == "Test Page"
        assert meta.type == "ielts_topic"
        assert ("User Material") in body

    def test_create_page_default_sections(self, store: WikiStore):
        patch = _make_patch(operation="create_page", type="ielts_topic", slug="test/topic")
        store.apply_patch(patch)
        page = store.read_page("test/topic")
        assert page is not None
        _, body = page
        assert "## Summary" in body
        assert "## User Material" in body
        assert "## Useful Expressions" in body
        assert "## Weaknesses" in body

    def test_create_page_language_weakness_sections(self, store: WikiStore):
        patch = _make_patch(operation="create_page", type="language_weakness", slug="test/weak")
        store.apply_patch(patch)
        page = store.read_page("test/weak")
        assert page is not None
        _, body = page
        assert "## Examples" in body
        assert "## Corrections" in body


# ---------------------------------------------------------------------------
# merge_section deduplication
# ---------------------------------------------------------------------------

class TestMergeSectionDeduplication:
    def test_same_patch_twice_one_bullet(self, store: WikiStore):
        patch = _make_patch(operation="merge_section")
        store.apply_patch(patch)

        # Apply identical patch again
        patch2 = _make_patch(
            operation="merge_section",
            sources=[
                WikiSource(
                    kind="session",
                    session_id="def",
                    message_id="user:2",
                    timestamp="2026-05-27T11:00:00+08:00",
                )
            ],
        )
        result = store.apply_patch(patch2)
        assert result is True

        page = store.read_page("test/page")
        assert page is not None
        _, body = page
        # Bullet should appear only once
        bullets = [l for l in body.splitlines() if "User enjoys basketball" in l]
        assert len(bullets) == 1

    def test_duplicate_adds_source(self, store: WikiStore):
        patch = _make_patch(operation="merge_section")
        store.apply_patch(patch)

        patch2 = _make_patch(
            operation="merge_section",
            sources=[
                WikiSource(
                    kind="session",
                    session_id="xyz",
                    message_id="user:99",
                )
            ],
        )
        store.apply_patch(patch2)

        sources = store.read_sources("test/page")
        assert sources is not None
        # Find the fact entry
        entries = list(sources.facts.values())
        assert len(entries) == 1
        entry = entries[0]
        # Two sources
        assert len(entry.sources) == 2
        assert entry.confirmations == 2

    def test_different_content_different_bullet(self, store: WikiStore):
        patch = _make_patch(operation="merge_section", content="User enjoys basketball.")
        store.apply_patch(patch)

        patch2 = _make_patch(
            operation="merge_section",
            content="User also enjoys volleyball.",
            sources=[WikiSource(kind="session", session_id="b", message_id="m:2")],
        )
        store.apply_patch(patch2)

        page = store.read_page("test/page")
        assert page is not None
        _, body = page
        assert "User enjoys basketball" in body
        assert "User also enjoys volleyball" in body


# ---------------------------------------------------------------------------
# append_section
# ---------------------------------------------------------------------------

class TestAppendSection:
    def test_append_adds_bullet_every_time(self, store: WikiStore):
        store.apply_patch(_make_patch(operation="create_page"))
        for i in range(3):
            store.apply_patch(
                _make_patch(
                    operation="append_section",
                    section="Log",
                    content=f"Event {i}",
                    sources=[WikiSource(kind="session", session_id=f"s{i}")],
                )
            )
        page = store.read_page("test/page")
        assert page is not None
        _, body = page
        # append_section never deduplicates
        assert body.count("Event 0") == 1
        assert body.count("Event 1") == 1
        assert body.count("Event 2") == 1


# ---------------------------------------------------------------------------
# replace_section
# ---------------------------------------------------------------------------

class TestReplaceSection:
    def test_replace_section_requires_reason(self, store: WikiStore):
        # apply_patch catches all exceptions internally and returns False
        patch = _make_patch(operation="replace_section", content="New content")
        result = store.apply_patch(patch)
        assert result is False

    def test_replace_section_works(self, store: WikiStore):
        store.apply_patch(_make_patch(operation="create_page"))
        store.apply_patch(
            _make_patch(
                operation="replace_section",
                section="Summary",
                content="New summary content.",
                reason="Updating outdated info.",
            )
        )
        page = store.read_page("test/page")
        assert page is not None
        _, body = page
        assert "New summary content." in body


# ---------------------------------------------------------------------------
# add_link
# ---------------------------------------------------------------------------

class TestAddLink:
    def test_add_link_merges_links(self, store: WikiStore):
        store.apply_patch(_make_patch(operation="create_page"))
        store.apply_patch(
            _make_patch(
                operation="add_link",
                links=["extra/link"],
                sources=[WikiSource(kind="manual")],
            )
        )
        page = store.read_page("test/page")
        assert page is not None
        meta, _ = page
        assert "extra/link" in meta.links
        assert "user/preferences" in meta.links  # original link preserved


# ---------------------------------------------------------------------------
# deprecate_fact
# ---------------------------------------------------------------------------

class TestDeprecateFact:
    def test_deprecate_fact_marks_in_body(self, store: WikiStore):
        store.apply_patch(_make_patch(operation="merge_section"))
        store.apply_patch(
            _make_patch(operation="deprecate_fact", content="User enjoys basketball.")
        )
        page = store.read_page("test/page")
        assert page is not None
        _, body = page
        assert "[DEPRECATED]" in body


# ---------------------------------------------------------------------------
# update_summary
# ---------------------------------------------------------------------------

class TestUpdateSummary:
    def test_update_summary(self, store: WikiStore):
        store.apply_patch(_make_patch(operation="create_page"))
        store.apply_patch(
            _make_patch(
                operation="update_summary",
                content="Updated summary here.",
            )
        )
        page = store.read_page("test/page")
        assert page is not None
        _, body = page
        assert "Updated summary here." in body


# ---------------------------------------------------------------------------
# log.jsonl
# ---------------------------------------------------------------------------

class TestLogRecording:
    def test_patch_applied_logged(self, store: WikiStore):
        store.apply_patch(_make_patch(operation="create_page"))
        log_path = store._log_path
        assert log_path.exists()
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) >= 1
        event = json.loads(lines[0])
        assert event["event"] == "patch_applied"
        assert event["slug"] == "test/page"

    def test_rejected_patch_logged(self, store: WikiStore):
        # replace_section without a reason is rejected at apply time (not construction)
        bad_patch = _make_patch(
            operation="replace_section",
            content="New content",
            reason=None,  # explicitly no reason
        )
        store.apply_patch(bad_patch)
        log_path = store._log_path
        lines = log_path.read_text().strip().split("\n")
        reject_events = [json.loads(l) for l in lines if json.loads(l)["event"] == "patch_rejected"]
        assert len(reject_events) == 1


# ---------------------------------------------------------------------------
# list_pages
# ---------------------------------------------------------------------------

class TestListPages:
    def test_list_pages_empty(self, store: WikiStore):
        assert store.list_pages() == []

    def test_list_pages_returns_all(self, store: WikiStore):
        store.apply_patch(_make_patch(slug="page/one", title="One"))
        store.apply_patch(_make_patch(slug="page/two", title="Two"))
        pages = store.list_pages()
        assert len(pages) == 2


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

class TestNormalizeBullet:
    @pytest.mark.parametrize(
        "input_, expected",
        [
            ("- User likes basketball", "user likes basketball"),
            ("* i like basketball.", "i like basketball"),
            ("+  User enjoys volleyball  ", "user enjoys volleyball"),
            ("plain text", "plain text"),
        ],
    )
    def test_normalize(self, input_: str, expected: str):
        assert _normalize_bullet(input_) == expected


class TestSplitSections:
    def test_splits_by_headings(self):
        body = "## Summary\n\nSummary text.\n\n## User Material\n\nMaterial here.\n"
        sections = _split_sections(body)
        assert sections["Summary"] == "Summary text."
        assert sections["User Material"] == "Material here."

    def test_unnamed_section_first(self):
        body = "Intro text.\n\n## Section One\n\nContent."
        sections = _split_sections(body)
        assert sections[""] == "Intro text."
        assert sections["Section One"] == "Content."
