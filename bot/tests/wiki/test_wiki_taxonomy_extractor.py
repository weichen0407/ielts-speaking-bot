import json
from pathlib import Path

import pytest

from nanobot.agent.wiki_sync import sync_session_to_wiki
from nanobot.providers.base import LLMResponse
from subagent.cross_session.wiki.processor.wiki_ingest import IngestMessage
from subagent.cross_session.wiki.processor.wiki_llm_extractor import WikiLLMExtractor
from subagent.cross_session.wiki.processor.wiki_query import WikiQueryEngine
from subagent.cross_session.wiki.processor.wiki_taxonomy import WikiTaxonomy
from subagent.cross_session.wiki.processor.wiki_topic_review import TopicReviewQueue


class FakeExtractorProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    async def chat_with_retry(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(content=self.content)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _taxonomy() -> WikiTaxonomy:
    return WikiTaxonomy.load(_repo_root() / "config" / "wiki_taxonomy.yaml")


def test_taxonomy_loads_and_validates_default_config() -> None:
    taxonomy = _taxonomy()

    assert taxonomy.validate("sports", "football", "favorite_team")
    assert taxonomy.validate("travel", "city_trip", "travel_goal")
    assert not taxonomy.validate("sports", "football", "favorite_food")
    assert taxonomy.normalize("bad", "topic", "value") == (
        "other",
        "uncategorized",
        "unknown",
    )
    prompt = taxonomy.allowed_values_for_prompt()
    assert "sports/football" in prompt
    assert "other/uncategorized/unknown" in prompt


@pytest.mark.asyncio
async def test_llm_extractor_parses_taxonomy_guided_candidates() -> None:
    provider = FakeExtractorProvider(
        "\n".join(
            [
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
                            {
                                "subject": "user",
                                "predicate": "supports",
                                "object": "Arsenal",
                            }
                        ],
                        "source_refs": ["thread:s1:m4"],
                        "confidence": "high",
                        "candidate_new_topic": None,
                    }
                ),
                json.dumps(
                    {
                        "domain": "travel",
                        "topic": "city_trip",
                        "subtype": "travel_goal",
                        "wiki_type": "entity",
                        "title": "Paris Football Travel Goal",
                        "content": "User wants to go to Paris to watch a football match.",
                        "entities": ["Paris"],
                        "relations": [
                            {
                                "subject": "user",
                                "predicate": "wants_to_visit",
                                "object": "Paris",
                            }
                        ],
                        "source_refs": ["thread:s1:m3"],
                        "confidence": "high",
                        "candidate_new_topic": None,
                    }
                ),
            ]
        )
    )
    messages = [
        IngestMessage(
            line_no=1,
            event_id="m3",
            session_id="s1",
            message_index=3,
            role="user",
            text="I want to go to Paris to watch a football match someday.",
            timestamp=None,
            raw={},
        ),
        IngestMessage(
            line_no=2,
            event_id="m4",
            session_id="s1",
            message_index=4,
            role="user",
            text="My favorite club is Arsenal.",
            timestamp=None,
            raw={},
        ),
    ]

    extractor = WikiLLMExtractor(provider=provider, model="test-model", taxonomy=_taxonomy())
    result = extractor.parse_output(provider.content, messages)

    assert result.invalid_lines == 0
    assert len(result.candidates) == 2
    assert result.candidates[0].type == "entity"
    assert "domain:sports" in result.candidates[0].tags
    assert "entity:Arsenal" in result.candidates[0].tags
    assert result.candidates[0].topics == ["sports/football"]
    assert "user supports Arsenal" in result.candidates[0].content


def test_topic_review_queue_merges_repeated_suggestions(tmp_path: Path) -> None:
    queue = TopicReviewQueue(tmp_path / "topic_review_queue.jsonl")
    item = queue.upsert(
        queue_item(
            "sports",
            "football_travel",
            ["thread:s1:m1"],
            ["I like football travel."],
        )
    )
    merged = queue.upsert(
        queue_item(
            "sports",
            "football_travel",
            ["thread:s2:m5"],
            ["I want to travel for football matches."],
        )
    )

    assert item.suggested_topic == "football_travel"
    assert merged.evidence_count == 2
    loaded = queue.load()
    assert len(loaded) == 1
    assert loaded[0].source_refs == ["thread:s1:m1", "thread:s2:m5"]


@pytest.mark.asyncio
async def test_wiki_sync_optionally_runs_taxonomy_extractor(tmp_path: Path, monkeypatch) -> None:
    session_uuid = "travel-football-session"
    data_dir = tmp_path / "persona" / "events"
    data_dir.mkdir(parents=True)
    events = [
        {
            "id": "m1",
            "source": {"mode": "freechat", "session_uuid": session_uuid, "message_index": 1},
            "role": "user",
            "content": {"type": "text", "text": "I really like basketball."},
        },
        {
            "id": "m2",
            "source": {"mode": "freechat", "session_uuid": session_uuid, "message_index": 2},
            "role": "user",
            "content": {"type": "text", "text": "My favorite club is Arsenal."},
        },
    ]
    (data_dir / "thread.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
    provider = FakeExtractorProvider(
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
                "source_refs": [f"thread:{session_uuid}:m2"],
                "confidence": "high",
                "candidate_new_topic": None,
            },
            ensure_ascii=False,
        )
    )
    monkeypatch.setenv("NANOBOT_WIKI_LLM_EXTRACTOR", "1")

    result = await sync_session_to_wiki(
        session_key=session_uuid,
        session_dir=str(tmp_path / "persona" / "sessions" / session_uuid),
        workspace=tmp_path,
        provider=provider,
        model="test-model",
    )

    assert result["status"] == "ok"
    assert result["llm_extractor_enabled"] is True
    assert result["llm_candidates"] == 1
    assert provider.calls
    query = WikiQueryEngine(wiki_root=tmp_path / "persona" / "wiki").query(
        "Arsenal",
        limit=5,
    )
    assert any(item.type == "entity" for item in query)


def queue_item(domain: str, topic: str, refs: list[str], samples: list[str]):
    from subagent.cross_session.wiki.processor.wiki_topic_review import TopicReviewItem

    return TopicReviewItem(
        suggested_domain=domain,
        suggested_topic=topic,
        reason="test",
        source_refs=refs,
        sample_messages=samples,
        evidence_count=len(refs),
        created_at="2026-06-02T00:00:00",
        updated_at="2026-06-02T00:00:00",
    )
