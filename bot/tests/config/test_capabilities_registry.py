from pathlib import Path

from nanobot.config.capabilities import load_capabilities


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
