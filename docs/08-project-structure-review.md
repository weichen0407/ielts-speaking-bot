# Project Structure Review

> Date: 2026-05-31  
> Purpose: Record current project-level weaknesses and turn them into concrete discussion topics before restructuring.

## 0. Summary

The project is now feature-rich: WebUI, subagents, notes, wiki, monitor, cron, persona memory, mode-specific triggers, and external speech components are all present. The main risk is no longer missing capability. The main risk is that too many layers now overlap without a single canonical map.

This document lists the current shortcomings, why they matter, possible fixes, and questions that need product/architecture decisions.

## 1. Runtime Data Paths Are Duplicated

### Decision

Use a single clean runtime data root. The working decision is to use `persona/`
as the canonical root for user-owned runtime data, unless a better name is
chosen before implementation. The name matters less than having exactly one
authoritative location for each data type.

Accepted decisions:

- `persona/` is the canonical runtime root for user/business data.
- Keep the global derived event stream, but move it to `persona/events/thread.jsonl`.
- Test runtime data in old root-level folders can be deleted.
- Keep `monitor/` at the project root because it is system observability rather than user learning data.
- Move cron and count runtime state under `persona/trigger/`.

### Current Symptoms

Several directories appear to represent similar or overlapping runtime state:

- `data/thread.jsonl`
- `data/thread.jsonl.bak-20260529-163515`
- `sessions/`
- `persona/sessions/`
- `memory/`
- `persona/memory/`
- `trigger/cron/jobs.json`
- `persona/trigger/cron/jobs.json`
- `persona/cron/jobs.json`

### Why This Matters

When the same kind of data can live in multiple places, it becomes hard to answer basic operational questions:

- Which file is the true source of conversation history?
- Which memory file does the agent actually read?
- Which cron store is active?
- Is a file stale, migrated, or still used?

This creates debugging risk, especially for subagent and wiki pipelines that depend on historical records.

### Possible Direction

Define canonical runtime paths:

- `persona/sessions/` as the only session source.
- `persona/memory/` as the only long-term memory source.
- `persona/wiki/` as the only wiki source.
- `monitor/` for observability logs.
- Choose either `trigger/` or `persona/trigger/` for active trigger state.

Legacy paths should be either migrated, archived, or explicitly marked read-only.

### Implementation Notes

The first cleanup pass updated the active code and prompt references that were
still pointing at old root-level paths:

- Memory readers/writers now use `persona/memory/MEMORY.md`.
- The derived interaction log now writes to `persona/events/thread.jsonl`.
- Cron cursor state now writes to `persona/trigger/cron/`.
- Count/file-line cursor state now writes to `persona/trigger/count/`.
- Root-level test data directories were removed.

Proposed canonical mapping:

| Data Type | Canonical Path | Treatment Of Old Path |
| --- | --- | --- |
| Per-session raw chat | `persona/sessions/{session_uuid}/thread.jsonl` | Old root `sessions/` test data deleted. |
| Global derived event stream | `persona/events/thread.jsonl` | Delete old `data/thread.jsonl` test data. |
| Long-term memory | `persona/memory/MEMORY.md` | Old root `memory/` test data deleted. |
| Memory history | `persona/memory/history.jsonl` | Empty runtime log; ignored by git. |
| Wiki | `persona/wiki/` | Choose one canonical page subtree. |
| Trigger runtime state | `persona/trigger/` | Old root `trigger/` deleted. |
| Monitor logs | `monitor/` | Keep at root as system observability. |

### Questions

Resolved:

1. `persona/` is canonical for user-owned runtime data.
2. The global derived event stream stays, moved to `persona/events/thread.jsonl`.
3. Old test data can be deleted rather than archived.
4. `monitor/` stays at the project root.
5. Cron and count state live under `persona/trigger/`.

## 2. Architecture Documentation Is Behind The Code

### Status

Resolved in the current cleanup pass. `architecture.md` has been rewritten as
a current-state architecture document instead of a historical prototype map.

### Current Symptoms

`architecture.md` still contains outdated assumptions:

- `memory_cron` / `daily_consolidator` described as timestamp + mtime based.
- Old model references such as `gpt-4o-mini`.
- Old global/mode trigger descriptions that no longer fully match the current JSON trigger files.
- Some wiki and monitor behavior is not reflected.

### Why This Matters

When architecture docs lag behind implementation, future debugging starts from false premises. This is especially dangerous in this project because many behaviors are indirect: cron schedules, subagent triggers, cursor files, monitor rendering, and wiki sync all happen in the background.

### Possible Direction

Replace or heavily update `architecture.md` with a smaller current-state architecture document:

- Runtime data map.
- Trigger lifecycle.
- Subagent lifecycle.
- Wiki lifecycle.
- Monitor/logging lifecycle.
- Canonical file ownership table.

### Questions

Resolved:

1. `architecture.md` remains the main high-level architecture document.
2. It now uses both flow diagrams and file ownership tables.
3. It describes the current implementation; planned direction stays in separate planning docs.

## 3. Trigger Decisions Are Not Observable Enough

### Status

Resolved in the current cleanup pass. Trigger decisions now write to
`monitor/trigger_decisions.jsonl` and are rendered in the WebUI monitor.

### Current Symptoms

The monitor can show subagent runs, but it does not fully show why a subagent did or did not run.

Missing visibility includes:

- Current turn count per session.
- Trigger interval and next eligible turn.
- Cursor offset before and after processing.
- Whether a trigger was skipped because mode did not match.
- Whether a cron job found no deltas.
- Whether a subagent was not called because a prompt or model config was missing.

### Why This Matters

When testing, "nothing happened" is ambiguous. It could mean:

- Trigger condition was not met.
- The wrong mode was active.
- The subagent failed before logging.
- The frontend did not render the result.
- The cursor already consumed the source.

Without trigger decision logs, debugging requires reading multiple files manually.

### Possible Direction

Add a `monitor/trigger_decisions.jsonl` or similar log.

Each entry could include:

```json
{
  "timestamp": "...",
  "trigger_id": "vocab",
  "mode": "freechat",
  "session_uuid": "...",
  "kind": "turn_count",
  "decision": "skipped|spawned|failed|no_delta",
  "reason": "...",
  "cursor_before": {},
  "cursor_after": {},
  "subagent_task_id": "..."
}
```

The WebUI monitor can then show both positive and negative decisions.

### Questions

Resolved:

1. Log every meaningful trigger check, including skipped, no-delta, eligible, spawned, and failed.
2. Show it in the current monitor page for now.
3. Retention is still open; logs are append-only and ignored by git.

## 4. Subagent, Processor, And Tool Boundaries Are Blurry

### Current Symptoms

Several capabilities exist in multiple forms:

- Notes has both a tool and a cross-session subagent.
- Wiki has tool APIs, processors, data stores, and WebUI rendering.
- Progress tracking has trigger config, tool cursor logic, and processor/subagent context.

This is flexible, but the naming does not always tell whether a module is:

- An LLM subagent.
- A deterministic processor.
- A runtime tool exposed to the agent.
- A WebUI/API helper.

### Why This Matters

When behavior is not visible in the name or directory, it becomes hard to answer:

- Is this called by LLM?
- Is this deterministic code?
- Is this user-triggered or background-triggered?
- Does this write runtime data?

This also makes future subagents easy to duplicate accidentally.

### Possible Direction

Introduce a role convention:

- `subagent/*/context/` for LLM instructions.
- `subagent/*/processor/` for deterministic post-processing.
- `bot/nanobot/agent/tools/` for callable agent tools.
- `bot/nanobot/channels/` for WebUI/API transport.
- A small registry document listing each capability and its role.

### Questions

1. Should every subagent have a README describing inputs, outputs, trigger, and storage?
2. Should tools that spawn subagents be renamed to make that explicit?
3. Should deterministic wiki processors stay under `subagent/`, or move into `bot/nanobot/wiki/`?

## 5. Wiki Storage Has Duplicate-Looking Trees

### Current Symptoms

Before cleanup, `persona/wiki/` included both:

- `persona/wiki/pages/`
- `persona/wiki/wiki/`

Both appear to contain similar page files and `.sources.json` files.

### Why This Matters

Wiki is becoming a core memory layer. If there are two page trees, readers and writers may diverge:

- WebUI may render one tree.
- Query may search another.
- Lint may validate only one.
- Sync may write to a different one.

This can make wiki changes appear to disappear.

### Possible Direction

Resolved direction:

- `persona/wiki/wiki/` is the canonical editable page store.
- `persona/wiki/pages/` was legacy prototype output and can be removed after confirming contents are copied.
- Generated indexes live under `persona/wiki/index/`.

### Questions

Resolved:

1. Canonical page directory: `persona/wiki/wiki/`.
2. WebUI/API should read through `WikiStore`, which uses the canonical layout.
3. Generated indexes live only under `persona/wiki/index/`.

## 6. Development Environment And Vendor Code Are Heavy

### Current Symptoms

Large local directories exist inside the project:

- `.venv` around 1.3G.
- `bot/.venv` around 1.3G.
- `bot/webui/node_modules` around 473M.
- `WhisperLiveKit` around 919M.

### Why This Matters

This makes search, backup, tooling, and mental navigation slower. It also increases the chance that local-only artifacts are accidentally considered part of the project.

### Possible Direction

- Keep only one Python virtual environment if possible.
- Treat `WhisperLiveKit` as a submodule, `vendor/` dependency, or external sibling repo.
- Confirm `.gitignore` excludes runtime-heavy directories.
- Add a short local setup doc explaining which env is authoritative.

### Questions

1. Should the authoritative Python environment be root `.venv` or `bot/.venv`?
2. Is `WhisperLiveKit` intended to be edited as part of this repo, or treated as an external dependency?
3. Do you want a `vendor/` directory convention?

## 7. Current Git Working Tree Needs Commit Boundaries

### Current Symptoms

The current working tree contains multiple logical changes at once:

- DeepSeek model/config changes.
- Monitor cost summary.
- WebUI monitor updates.
- Cron incremental processing.
- Trigger config changes.
- Subagent prompt updates.
- New cron tests.

### Why This Matters

If one change breaks something, rollback becomes hard. It is also difficult to review or reason about which behavior changed because of which patch.

### Possible Direction

Split into small commits:

1. Model/config and cost monitor.
2. Cron incremental cursor processing.
3. Trigger/subagent prompt cleanup.
4. Wiki/WebUI graph work.
5. Documentation updates.

### Questions

1. Do you want to preserve the current working tree as one checkpoint commit first?
2. Or should we split the current changes into topic commits?
3. Should runtime data files be committed, ignored, or archived outside git?

## 8. Runtime Logs And Generated Data Need A Retention Policy

### Current Symptoms

Runtime files exist in project-visible paths:

- `monitor/subagent_runs.jsonl`
- `persona/events/thread.jsonl`
- session `thread.jsonl` files
- wiki logs and indexes
- cursor files
- backup files

### Why This Matters

Some files are valuable training/debugging traces. Others are generated state. Without a policy, they accumulate and make the repo harder to reason about.

### Possible Direction

Classify files as:

- Source-controlled config.
- Runtime state.
- Generated cache/index.
- Debug log.
- Archive/migration backup.

Then update `.gitignore` and docs accordingly.

### Questions

1. Should personal runtime data be committed to git at all?
2. Should monitor logs rotate by size/date?
3. Should backups like `thread.jsonl.bak-*` be moved to an archive directory?

## 9. Suggested Discussion Order

Recommended order for decisions:

1. Choose canonical runtime paths.
2. Decide wiki canonical page root.
3. Decide trigger/monitor observability shape.
4. Clarify subagent/tool/processor boundaries.
5. Clean generated/runtime files.
6. Update architecture docs.
7. Split or checkpoint git changes.

The first two decisions affect many later choices, so they should happen before any large refactor.
