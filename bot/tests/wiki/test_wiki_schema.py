"""Tests for wiki schema validation."""

import pytest
from pydantic import ValidationError

from subagent.cross_session.wiki.processor.schema import (
    ALLOWED_PAGE_TYPES,
    WikiPatch,
    WikiPageMeta,
    WikiSearchResult,
    WikiSource,
    WikiSourcesData,
    WikiSourcesEntry,
)


class TestWikiSource:
    def test_valid_source(self):
        src = WikiSource(kind="session", session_id="abc", message_id="user:1")
        assert src.kind == "session"
        assert src.session_id == "abc"

    def test_source_optional_fields(self):
        src = WikiSource(kind="file", file="vocab.jsonl")
        assert src.file == "vocab.jsonl"
        assert src.session_id is None


class TestWikiPatchSlugValidation:
    def _patch(self, **kw) -> WikiPatch:
        defaults = dict(
            operation="merge_section",
            slug="test/slug",
            title="Test",
            type="ielts_topic",
            mode="ielts",
            sources=[WikiSource(kind="session", session_id="x", message_id="m:1")],
        )
        defaults.update(kw)
        return WikiPatch(**defaults)

    # -- Good slugs --

    @pytest.mark.parametrize(
        "slug",
        [
            "a",
            "a/b",
            "a_b",
            "a-b",
            "user/profile",
            "ielts/topics/sports-2024",
            "a/b/c/d",
            "freechat/ideas",
            "language/vocabulary",
        ],
    )
    def test_good_slug(self, slug: str):
        p = self._patch(slug=slug)
        assert p.slug == slug

    # -- Bad slugs --

    @pytest.mark.parametrize(
        "slug, expected_msg",
        [
            ("/test", "must not start with '/'"),
            ("../x", "must not contain '..'"),
            ("x/../../y", "must not contain '..'"),
            ("x y", "must match"),
            ("UPPER", "must match"),
            ("-test", "must match"),
            ("", "must match"),
            ("abc/..", "must not contain '..'"),
        ],
    )
    def test_bad_slug_rejected(self, slug: str, expected_msg: str):
        with pytest.raises(ValidationError, match=expected_msg):
            self._patch(slug=slug)


class TestWikiPatchTypeValidation:
    def _patch(self, **kw) -> WikiPatch:
        defaults = dict(
            operation="merge_section",
            slug="test/slug",
            title="Test",
            type="ielts_topic",
            mode="ielts",
            sources=[WikiSource(kind="session", session_id="x", message_id="m:1")],
        )
        defaults.update(kw)
        return WikiPatch(**defaults)

    @pytest.mark.parametrize("page_type", sorted(ALLOWED_PAGE_TYPES))
    def test_good_page_type(self, page_type: str):
        p = self._patch(type=page_type)
        assert p.type == page_type

    def test_bad_page_type_rejected(self):
        with pytest.raises(ValidationError, match="Unknown page type"):
            self._patch(type="not_a_real_type")


class TestWikiPatchModeValidation:
    def _patch(self, **kw) -> WikiPatch:
        defaults = dict(
            operation="merge_section",
            slug="test/slug",
            title="Test",
            type="ielts_topic",
            mode="ielts",
            sources=[WikiSource(kind="session", session_id="x", message_id="m:1")],
        )
        defaults.update(kw)
        return WikiPatch(**defaults)

    @pytest.mark.parametrize("mode", ["global", "ielts", "freechat", "benative", "language"])
    def test_good_mode(self, mode: str):
        p = self._patch(mode=mode)
        assert p.mode == mode

    def test_bad_mode_rejected(self):
        with pytest.raises(ValidationError, match="should be"):
            self._patch(mode="invalid_mode")


class TestWikiPatchSourcesRequired:
    def _patch(self, **kw) -> WikiPatch:
        defaults = dict(
            operation="merge_section",
            slug="test/slug",
            title="Test",
            type="ielts_topic",
            mode="ielts",
            sources=[WikiSource(kind="session", session_id="x", message_id="m:1")],
        )
        defaults.update(kw)
        return WikiPatch(**defaults)

    def test_write_without_sources_rejected(self):
        with pytest.raises(ValueError, match="requires at least one source"):
            self._patch(sources=[])

    def test_add_link_without_sources_accepted(self):
        # add_link and deprecate_fact don't require sources
        p = self._patch(operation="add_link", sources=[])
        assert p.operation == "add_link"

    def test_deprecate_fact_without_sources_accepted(self):
        p = self._patch(operation="deprecate_fact", sources=[])
        assert p.operation == "deprecate_fact"


class TestWikiPageMeta:
    def test_valid_meta(self):
        meta = WikiPageMeta(
            slug="ielts/topics/sports",
            title="Sports",
            type="ielts_topic",
            mode="ielts",
            tags=["sports", "hobbies"],
            topics=["sports"],
            links=["user/preferences"],
            updated_at="2026-05-27T10:00:00+08:00",
        )
        assert meta.slug == "ielts/topics/sports"
        assert meta.tags == ["sports", "hobbies"]

    def test_meta_bad_slug_rejected(self):
        with pytest.raises(ValidationError, match="must not start with '/'"):
            WikiPageMeta(
                slug="/bad",
                title="Bad",
                type="ielts_topic",
                mode="ielts",
                updated_at="2026-05-27",
            )

    def test_meta_bad_type_rejected(self):
        with pytest.raises(ValidationError, match="Unknown page type"):
            WikiPageMeta(
                slug="good/slug",
                title="Good",
                type="bad_type",
                mode="ielts",
                updated_at="2026-05-27",
            )


class TestWikiSourcesData:
    def test_empty_sources_data(self):
        data = WikiSourcesData()
        assert data.facts == {}

    def test_sources_entry(self):
        entry = WikiSourcesEntry(
            text="User likes basketball.",
            section="User Material",
            sources=[WikiSource(kind="session", session_id="abc", message_id="u:1")],
            confirmations=1,
            first_seen="2026-05-27T10:00:00+08:00",
            last_seen="2026-05-27T10:00:00+08:00",
        )
        assert entry.text == "User likes basketball."
        assert entry.confirmations == 1


class TestWikiSearchResult:
    def test_valid_search_result(self):
        r = WikiSearchResult(
            slug="ielts/topics/sports",
            title="Sports",
            type="ielts_topic",
            mode="ielts",
            section="User Material",
            snippet="User enjoys basketball...",
            score=2.5,
            tags=["sports"],
            topics=["sports"],
        )
        assert r.slug == "ielts/topics/sports"
        assert r.score == 2.5
