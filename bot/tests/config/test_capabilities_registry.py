import json
from pathlib import Path

from nanobot.config.capabilities import (
    load_capabilities,
    wiki_mode_allowed,
    wiki_sync_allowed_modes,
    wiki_sync_allowed_roles,
    wiki_sync_interval,
)
from scripts.validate_subagent_config import validate_config


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


def test_capability_registry_matches_trigger_targets() -> None:
    root = Path(__file__).resolve().parents[3]

    result = validate_config(root)

    assert result["ok"] is True
    assert result["errors"] == []
    assert "vocab" in result["registered_subagents"]
    assert "deepseek-v4-flash" in result["registered_models"]
    assert "thread_query" in result["registered_tools"]


def test_validator_rejects_unknown_model(tmp_path: Path) -> None:
    _write_minimal_registry(tmp_path, target_overrides={"model": "gpt-4o-mini"})

    result = validate_config(tmp_path)

    assert result["ok"] is False
    assert any("model missing from config/capabilities.yaml models" in error for error in result["errors"])


def test_validator_rejects_processor_output_contract_mismatch(tmp_path: Path) -> None:
    _write_minimal_registry(tmp_path, target_overrides={"output_path": "persona/processor/freechat/vocab.md"})

    result = validate_config(tmp_path)

    assert result["ok"] is False
    assert any("artifact_type=jsonl" in error for error in result["errors"])


def test_validator_rejects_prompt_outside_subagent_directory(tmp_path: Path) -> None:
    _write_minimal_registry(
        tmp_path,
        subagent_prompt="subagent/single_session/other/context/vocab_subagent.md",
    )

    result = validate_config(tmp_path)

    assert result["ok"] is False
    assert any("prompt must live under subagent/single_session/vocab" in error for error in result["errors"])


def test_validator_rejects_deprecated_subagent_even_when_trigger_disabled(tmp_path: Path) -> None:
    _write_minimal_registry(
        tmp_path,
        trigger_enabled=False,
        target_overrides={
            "subagent": "old_vocab",
            "processor": "",
            "output_path": "",
        },
    )

    result = validate_config(tmp_path)

    assert result["ok"] is False
    assert any("subagent old_vocab is deprecated" in error for error in result["errors"])


def _write_minimal_registry(
    root: Path,
    *,
    subagent_prompt: str = "subagent/single_session/vocab/context/vocab_subagent.md",
    trigger_enabled: bool = True,
    target_overrides: dict[str, object] | None = None,
) -> None:
    prompt_path = root / subagent_prompt
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("# Vocab\n", encoding="utf-8")
    (root / "subagent/single_session/vocab/processor").mkdir(parents=True, exist_ok=True)
    (root / "mode/freechat/trigger").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)

    target: dict[str, object] = {
        "processor": "vocab",
        "subagent": "vocab",
        "execution_mode": "api",
        "agentic": False,
        "tools": [],
        "input_path": "persona/events/thread.jsonl",
        "output_path": "persona/processor/freechat/vocab.jsonl",
        "batch_size": 20,
        "model": "deepseek-v4-flash",
    }
    target.update(target_overrides or {})

    (root / "mode/freechat/trigger/triggers.json").write_text(
        json.dumps(
            {
                "version": 1,
                "triggers": [
                    {
                        "id": "freechat_vocab",
                        "enabled": trigger_enabled,
                        "condition": {"kind": "file_line_count", "count": 1},
                        "target": target,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (root / "config/capabilities.yaml").write_text(
        f"""
version: 1
models:
  deepseek-v4-flash:
    provider: deepseek
modes:
  freechat:
    trigger_file: mode/freechat/trigger/triggers.json
    subagents: [vocab]
subagents:
  vocab:
    scope: single_session
    prompt: {subagent_prompt}
    trigger_ids: [freechat_vocab]
    execution_modes: [api]
    default_execution_mode: api
    tools:
      api: []
    writes:
      - persona/sessions/{{session_uuid}}/notes/vocab.md
processors:
  vocab:
    path: subagent/single_session/vocab/processor
    status: active
    artifact_type: jsonl
    output: persona/processor/freechat/vocab.jsonl
    mode_outputs:
      freechat: persona/processor/freechat/vocab.jsonl
tools: {{}}
deprecated:
  subagents:
    old_vocab:
      replacement: subagents.vocab
      reason: test deprecated entry
""".lstrip(),
        encoding="utf-8",
    )
