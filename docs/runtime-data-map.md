# Runtime Data Map

This project has three different kinds of files:

- Source and prompt configuration: committed code, mode prompts, trigger definitions, and subagent implementations.
- Runtime event data: session logs, the global conversation event stream, and user-expression records.
- Derived runtime data: summaries, dashboards, indexes, and caches that can be rebuilt from runtime event data.

## Canonical Runtime Data

| Path | Purpose | Writer |
| --- | --- | --- |
| `persona/sessions/{session_uuid}/thread.jsonl` | Per-session conversation history. This is the canonical source for a single chat session. | `SessionManager.save()` |
| `data/thread.jsonl` | Global cross-session conversation event stream. It contains user and assistant turns from all sessions. | `SessionManager._sync_shared_interaction_log()` |
| `persona/session_index.jsonl` | Session list and metadata used to find sessions quickly. | `SessionManager._update_session_index()` |
| `persona/user_responses.jsonl` | Cross-session stream of user answers for progress/wiki processing. | `SessionManager.append_user_expression()` |
| `persona/{mode}/sessions/{session_uuid}/responses.jsonl` | Mode-specific user response records, such as freechat or benative responses. | `SessionManager.append_mode_response()` |
| `user-notes/` | User-authored notes and AI note replies. | Notes UI and notes subagents |

## Derived Runtime Data

| Path | Purpose | Rebuild/cleanup note |
| --- | --- | --- |
| `persona/progress_bank.jsonl` | Extracted expression highlights before aggregation. | Derived from `persona/user_responses.jsonl`. |
| `persona/progress.json` | Aggregated progress summary. | Derived from `persona/progress_bank.jsonl`. |
| `persona/sessions/{session_uuid}/notes/{vocab,polisher,profile}.md` | Single-session subagent outputs. | Recreated by count-triggered subagents. |
| `persona/monitor/subagent_runs.jsonl` | Monitor dashboard history: subagent task, model, parameters, result, tool events, and errors. | Append-only dashboard log. |
| `persona/wiki/` | LLM wiki memory pages, SQLite index, graph metadata, and update cursors. | Pages are important runtime memory; indexes/cursors are derived. |

## Source-Like Configuration

| Path | Purpose |
| --- | --- |
| `mode/{mode}/context/` | Static mode context and prompt materials. |
| `mode/{mode}/trigger/` | Static trigger definitions. |
| `subagent/` | Subagent prompts and processor code. |
| `persona/mode/` | Workspace-level overrides for mode assets. Keep these separate from root `mode/`. |

## Trigger Testing

Turn-count subagents are configured in `mode/{mode}/trigger/triggers.json`.
The monitor page can update `condition.count` through:

```http
GET /api/admin/triggers?source=mode/freechat/trigger/triggers.json&id=vocab_analysis&count=1
```

The next user turn hot-reloads the changed trigger file before checking whether
subagents should run. For testing, set `count` to `1`; for normal usage, set it
back to `2`, `3`, or a larger interval.

## Cleanup Rules

- Delete or ignore `.DS_Store`, `__pycache__/`, `.pytest_cache/`, `.venv/`, and `bot/.venv/`.
- Treat `data/thread.jsonl` as the global conversation event stream. If it contains duplicated rows, run `uv run python scripts/dedupe_thread_log.py`.
- Do not delete `persona/mode/` unless you first confirm the workspace should stop overriding root mode assets.
- `persona/bot/nanobot/templates/` currently looks like an accidental copy of template assets, not a referenced runtime path. It can be removed after confirming it is not being used as a manual backup.

## Why Old `data/thread.jsonl` Duplicated Rows

Older code appended the entire session to `data/thread.jsonl` every time the session was saved. Because each global event row got a fresh UUID, the same message appeared many times with different `id` values. The stable identity is `source.session_uuid + source.message_index`, so the current sync code replaces the current session slice and uses `"{session_uuid}:{message_index}"` as the global event id.
