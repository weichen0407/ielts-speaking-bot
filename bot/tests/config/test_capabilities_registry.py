from pathlib import Path

from nanobot.config.capabilities import (
    load_capabilities,
    wiki_mode_allowed,
    wiki_sync_allowed_modes,
    wiki_sync_allowed_roles,
    wiki_sync_interval,
)


def test_freechat_registers_middleware_gated_subagents() -> None:
    root = Path(__file__).resolve().parents[3]

    capabilities = load_capabilities(root)

    freechat = capabilities["modes"]["freechat"]
    assert freechat["subagents"] == ["vocab", "polisher"]

    vocab = capabilities["subagents"]["vocab"]
    assert vocab["execution_modes"] == ["api", "agentic"]
    assert vocab["default_execution_mode"] == "api"
    assert vocab["tools"]["api"] == []
    assert vocab["tools"]["agentic"] == [
        "thread_query",
        "artifact_read",
        "user_profile",
        "wiki_query",
    ]

    polisher = capabilities["subagents"]["polisher"]
    assert polisher["execution_modes"] == ["api", "agentic"]
    assert polisher["default_execution_mode"] == "api"
    assert polisher["tools"]["api"] == []
    assert polisher["tools"]["agentic"] == [
        "thread_query",
        "artifact_read",
        "user_profile",
    ]

    tools = capabilities["tools"]
    for name in ["thread_query", "artifact_read", "user_profile", "wiki_query"]:
        assert tools[name]["scope"] == "read_only"


def test_wiki_sync_defaults_to_freechat_only() -> None:
    root = Path(__file__).resolve().parents[3]

    capabilities = load_capabilities(root)

    sync = capabilities["processors"]["wiki"]["sync"]
    assert sync["source"] == "persona/events/thread.jsonl"
    assert sync["interval"] == 1
    assert sync["allowed_modes"] == ["freechat"]
    assert sync["allowed_roles"] == ["user"]
    assert wiki_sync_interval(root) == 1
    assert wiki_sync_allowed_modes(root) == {"freechat"}
    assert wiki_sync_allowed_roles(root) == {"user"}
    assert wiki_mode_allowed("freechat", root) is True
    assert wiki_mode_allowed("benative", root) is False


def test_benative_registers_article_and_review_capabilities() -> None:
    root = Path(__file__).resolve().parents[3]

    capabilities = load_capabilities(root)

    benative = capabilities["modes"]["benative"]
    assert benative["subagents"] == [
        "benative_article",
        "benative_review",
    ]

    vocab = capabilities["subagents"]["vocab"]
    assert "benative_vocab" not in vocab["trigger_ids"]

    polisher = capabilities["subagents"]["polisher"]
    assert "benative_polisher" not in polisher["trigger_ids"]

    article = capabilities["subagents"]["benative_article"]
    assert article["scope"] == "cross_session"
    assert article["execution_modes"] == ["api", "agentic"]
    assert article["tools"]["api"] == []
    assert article["tools"]["agentic"] == [
        "user_profile",
        "wiki_query",
        "thread_query",
        "artifact_read",
    ]

    review = capabilities["subagents"]["benative_review"]
    assert review["execution_modes"] == ["api", "agentic"]
    assert review["tools"]["agentic"] == [
        "user_profile",
        "wiki_query",
        "thread_query",
        "artifact_read",
    ]

    processors = capabilities["processors"]
    assert processors["benative_article"]["output"] == "persona/processor/benative/article.jsonl"
    assert processors["benative_review"]["output"] == "persona/processor/benative/review.jsonl"
    assert "benative" not in processors["vocab"]["mode_outputs"]
    assert "benative" not in processors["polisher"]["mode_outputs"]

    deprecated = capabilities["deprecated"]["subagents"]
    assert deprecated["benative_article_fetcher"]["replacement"] == "subagents.benative_article"
    assert deprecated["benative_translator"]["replacement"] == "subagents.benative_article"
