# P1 Runtime Hardening Plan

Date: 2026-06-07

This document tracks the next priority tier after P0 cleanup. P1 focuses on correctness, observability, and debugging confidence for the processor / subagent / mode / tool runtime.

## Goal

Make every background capability explainable from config to output:

```text
mode trigger
-> registry validation
-> processor middleware
-> api or agentic subagent execution
-> artifact write
-> monitor event
-> WebUI surface
```

## Checklist

- [ ] 1. Strengthen registry as the runtime control plane.
- [ ] 2. Standardize processor cursor, delta, retry, and partial-write behavior.
- [ ] 3. Make monitor output session-aware and mode-aware for every processor-mediated subagent.
- [ ] 4. Harden LLM Wiki ingest / crystallize / lint as a reviewable memory pipeline.
- [ ] 5. Tighten Be Native runtime data flow and review visibility.
- [ ] 6. Add a focused P1 regression test matrix.

## Task 1: Registry Control Plane

Current state:

- `config/capabilities.yaml` lists modes, subagents, processors, tools, outputs, observability logs, and deprecated entries.
- `scripts/validate_subagent_config.py` validates trigger references and some mode/output consistency.

Work:

- Add validation for disabled trigger policy:
  - Disabled triggers may exist, but should not silently reference unregistered capabilities.
  - Deprecated capabilities should remain forbidden even when disabled.
- Add validation for model fields:
  - Every trigger with LLM execution should resolve a model from either trigger target, mode default, or global default.
  - Flag unexpected model names if a provider allowlist is introduced.
- Add validation for processor output contracts:
  - Each processor should declare expected output artifact type: `jsonl`, `md`, `graph`, or `mixed`.
  - Trigger output paths should match that contract.
- Add validation for subagent prompt ownership:
  - Prompt path should live under the registered subagent directory.
  - Cross-session prompts should not write session-only outputs unless explicitly declared.

Done when:

- `uv run python scripts/validate_subagent_config.py` catches stale, deprecated, misplaced, or mismatched runtime wiring before gateway startup.

## Task 2: Processor Cursor And Delta Semantics

Current state:

- Processors read append-only inputs and write derived artifacts.
- Some processors are session-scoped; some are cross-session.
- Dedupe and cursor behavior exists, but each capability still needs stronger guarantees.

Work:

- Define one shared cursor record shape:
  - `input_path`
  - `last_line`
  - `session_uuid`
  - `processor`
  - `trigger_id`
  - `updated_at`
  - `input_fingerprint`
- Make processors idempotent:
  - Re-running the same cursor range should not append duplicate artifacts.
  - Failed runs should not advance cursor.
- Add partial-write handling:
  - Write to temp file first when possible.
  - Append only validated records.
  - Record parse failures in `monitor/processor_runs.jsonl`.
- Keep processor as the only artifact writer:
  - Subagent / LLM output is treated as candidate material.
  - Processor validates, normalizes, and writes final artifacts.

Done when:

- A test can run the same processor twice and prove old rows are not processed twice.
- A malformed LLM result does not corrupt artifact files.

## Task 3: Monitor Session And Mode Visibility

Current state:

- Monitor logs include trigger decisions, subagent runs, processor runs, wiki sync, and cost summary.
- WebUI can show some processor/subagent status, but mode-specific result panels still need tighter routing.

Work:

- Make every processor run record include:
  - `mode`
  - `session_uuid`
  - `trigger_id`
  - `processor`
  - `subagent`
  - `execution_mode`
  - `model`
  - `tools`
  - `input_rows`
  - `output_rows`
  - `artifact_paths`
  - `status`
  - `error`
- Add session-scoped monitor queries:
  - Freechat should show `vocab` and `polisher`.
  - Be Native should show `review`.
  - IELTS should show IELTS-specific processors and feedback.
- Add "why did it not run?" visibility:
  - Trigger disabled.
  - Count threshold not reached.
  - Mode mismatch.
  - Dependency failed.
  - No new input rows.

Done when:

- After one user turn, WebUI can show whether each expected trigger ran, skipped, or failed, and where the output was written.

## Task 4: LLM Wiki Memory Pipeline Hardening

Current state:

- Wiki sync reads `persona/events/thread.jsonl`.
- Default policy allows only `freechat` + `user` turns.
- Ingest now filters obvious operational noise.

Work:

- Add a review queue before crystallization for lower-confidence candidates.
- Add conflict status:
  - `new`
  - `confirmed`
  - `contradicted`
  - `stale`
  - `needs_user_confirmation`
- Add taxonomy-guided golden tests:
  - hobbies: basketball, Arsenal, travel
  - places: Paris
  - learning goals: IELTS speaking fluency
  - preferences: topics user likes or avoids
- Add semantic lint:
  - Ensure source refs exist.
  - Ensure page frontmatter includes expected fields.
  - Ensure entity/concept pages do not store raw schema implementation details as user-facing graph nodes.

Done when:

- Wiki can explain why a memory exists, where it came from, and whether it is confirmed or uncertain.

## Task 5: Be Native Runtime Flow

Current state:

- Be Native uses fixed article/source data and a `benative_review` processor-mediated subagent.
- User answer should move immediately to the next sentence, while review runs asynchronously.

Work:

- Ensure seeded article sources are discoverable from UI and bootstrap.
- Ensure each user answer appends one review record under the current session.
- Add Be Native session summary:
  - article id
  - sentence count
  - completed sentence indexes
  - review artifact path
  - latest review status
- Keep vocab/polisher hidden for Be Native unless explicitly re-enabled.

Done when:

- A Be Native session can be replayed from stored records without reading transient UI state.

## Task 6: P1 Regression Matrix

Minimum tests:

- Registry validation catches deprecated subagent trigger references.
- Registry validation catches output path mode mismatch.
- Wiki ingest skips slash commands and accepts real freechat user facts.
- Processor re-run does not duplicate old artifacts.
- Be Native review appends per session and does not block the next sentence.
- Monitor API returns enough metadata to debug a skipped trigger.

## Verification Commands

- `uv run python scripts/validate_subagent_config.py`
- `uv run pytest bot/tests/config bot/tests/wiki bot/tests/subagent bot/tests/counter -q`
- `bun run check`
- `git diff --check`
