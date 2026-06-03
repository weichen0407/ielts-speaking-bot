# Runtime Data Map

This project has three different kinds of files:

- Source and prompt configuration: committed code, mode prompts, trigger definitions, and subagent implementations.
- Runtime event data: session logs, the global conversation event stream, and user-expression records.
- Derived runtime data: summaries, dashboards, indexes, and caches that can be rebuilt from runtime event data.

## Canonical Runtime Data

| Path | Purpose | Writer |
| --- | --- | --- |
| `persona/sessions/{session_uuid}/thread.jsonl` | Per-session conversation history. This is the canonical source for a single chat session. | `SessionManager.save()` |
| `persona/events/thread.jsonl` | Global cross-session conversation event stream. It contains user and assistant turns from all sessions. | `SessionManager._sync_shared_interaction_log()` |
| `persona/session_index.jsonl` | Session list and metadata used to find sessions quickly. | `SessionManager._update_session_index()` |
| `persona/user_responses.jsonl` | Cross-session stream of user answers for progress/wiki processing. | `SessionManager.append_user_expression()` |
| `persona/{mode}/sessions/{session_uuid}/responses.jsonl` | Mode-specific user response records, such as freechat or benative responses. | `SessionManager.append_mode_response()` |
| `persona/benative/articles/` | Benative source articles for translation practice. | `benative_article_fetcher` |
| `persona/benative/pairs/` | Sentence-level English/Chinese pairs for Benative practice. | `benative_translator` |
| `persona/benative/sessions/{session_uuid}/responses.jsonl` | Benative user translation attempts. | `SessionManager.append_mode_response()` |
| `user-notes/` | User-authored notes and AI note replies. | Notes UI and notes subagents |

## Derived Runtime Data

| Path | Purpose | Rebuild/cleanup note |
| --- | --- | --- |
| `persona/processor/{mode}/progress_tracker.jsonl` | Extracted expression highlights from incremental user response deltas. | Derived from `persona/{mode}/sessions/{session_uuid}/responses.jsonl` and processor cursors. |
| `persona/processor/{mode}/progress_organizer.jsonl` | Aggregated progress highlights materialized from progress tracker artifacts. | Derived from `persona/processor/{mode}/progress_tracker.jsonl`. |
| `persona/trigger/processor/.cursor_*.json` | Processor cursor state used to avoid reprocessing old artifacts. | Runtime state; safe to reset during tests. |
| `persona/sessions/{session_uuid}/notes/{vocab,polisher,profile}.md` | Single-session subagent outputs. | Recreated by count-triggered subagents. |
| `persona/wiki/` | LLM wiki memory pages, SQLite index, graph metadata, and update cursors. | Pages are important runtime memory; indexes/cursors are derived. |

## Observability Logs

| Path | Purpose | Rebuild/cleanup note |
| --- | --- | --- |
| `monitor/subagent_runs.jsonl` | Monitor dashboard history: subagent task, model, parameters, result, tool events, and errors. | Append-only system log. |
| `monitor/trigger_decisions.jsonl` | Trigger decision timeline: skipped, no-delta, eligible, spawned, and failed checks. | Append-only system log. |
| `persona/wiki/state/sync_log.jsonl` | Wiki sync run history and lint/application counts. | Wiki-local operation log. |

## Source-Like Configuration

| Path | Purpose |
| --- | --- |
| `mode/{mode}/context/` | Static mode context and prompt materials. |
| `mode/{mode}/trigger/` | Static trigger definitions. |
| `subagent/` | Subagent prompts and processor code. |
| `config/capabilities.yaml` | Canonical registry for modes, subagents, processors, runtime outputs, and monitor streams. |
| `persona/mode/` | Optional local workspace overrides for mode assets. It should normally be absent unless a workspace intentionally overrides root `mode/`. |

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
- Treat `persona/events/thread.jsonl` as the global conversation event stream. If it contains duplicated rows, run `uv run python scripts/dedupe_thread_log.py`.
- Runtime logs under `monitor/*.jsonl` are ignored and should not be committed.
- Keep deprecated planning material under `docs/deprecated/` so old paths do not appear as active implementation guidance.
- Remove stale local runtime/test data freely when it is not needed for a current manual test. The app should recreate ignored runtime files and directories as needed.

## Why Old `data/thread.jsonl` Duplicated Rows

Older code appended the entire session to `data/thread.jsonl` every time the session was saved. Because each global event row got a fresh UUID, the same message appeared many times with different `id` values. The stable identity is `source.session_uuid + source.message_index`, so the current sync code replaces the current session slice and uses `"{session_uuid}:{message_index}"` as the global event id.
