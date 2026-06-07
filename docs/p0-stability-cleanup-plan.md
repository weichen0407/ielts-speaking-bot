# P0 Stability Cleanup Plan

Date: 2026-06-07

This document tracks the immediate P0 cleanup pass for the processor / subagent / wiki runtime. The goal is to remove stale runtime surfaces, make tests quiet and repeatable, and strengthen registry validation before adding more capability layers.

## Checklist

- [x] 1. Archive deprecated Be Native subagent prompts and remove them from runtime paths.
- [x] 2. Fix the root pytest entrypoint so async tests run without config warnings.
- [x] 3. Add LLM Wiki ingest noise filtering for slash commands, test messages, and system-like chatter.
- [x] 4. Extend capability validation for deprecated subagent references and mode-scoped processor output paths.

## Notes

- Deprecated content is kept under `docs/deprecated/` for historical review, but should not appear under `subagent/` if it is no longer callable.
- Root-level validation should be runnable with `uv run pytest ...` and `uv run python scripts/validate_subagent_config.py`.

## Verification

- `uv run python scripts/validate_subagent_config.py`
- `uv run pytest bot/tests/wiki/test_wiki_sync.py -q`
- `uv run pytest bot/tests/wiki/test_wiki_core_pipeline.py bot/tests/wiki/test_wiki_sync.py bot/tests/config/test_capabilities_registry.py bot/tests/counter/test_benative_triggers.py -q`
- `git diff --check`
