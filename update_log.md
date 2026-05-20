# Update Log

## 2026-05-21 - Subagent Reorganization + Chained Triggers + Engineering Optimizations

This update reorganizes subagents into `session/` and `cross_session/` directories, implements trigger chaining (progress_organizer fires after progress_tracker), adds per-subagent model selection, and applies engineering optimizations to reduce token usage.

---

## 1. Subagent Folder Reorganization

### New Directory Structure
```
persona/subagents/
  session/
    vocab_subagent.md
    polisher_subagent.md
    memory_subagent.md
  cross_session/
    progress_tracker_subagent.md
    progress_organizer_subagent.md   # NEW
```

### Changes
- Moved session-level subagents (vocab, polisher, memory) to `persona/subagents/session/`
- Moved cross-session subagents (progress_tracker) to `persona/subagents/cross_session/`
- Created new `persona/subagents/cross_session/progress_organizer_subagent.md`
- Updated `triggers.yaml` `prompt_file` paths to new directory structure

---

## 2. CounterTrigger Schema Enhancements

### New Fields in `CounterTarget`

**bot/nanobot/counter/types.py**
- Added `depends_on: str | None` — trigger ID that must complete before this fires
- Added `model: str | None` — override default model for this subagent (e.g., "gpt-4o-mini")

### Unified `count` Field
- Replaced deprecated `every` and `threshold` fields with unified `count` field
- `triggers.yaml` updated: `every: 2` → `count: 2`, `every: 3` → `count: 3`, etc.

---

## 3. SubagentManager — Awaitable Completion Handle

### New Features

**bot/nanobot/agent/subagent.py**
- Added `completion_event: asyncio.Event` to `SubagentStatus` — fires when subagent finishes
- Added `wait_for_subagent(task_id)` method — awaits completion event, returns final status
- `spawn()` now returns `task_id` (string) instead of human-readable message
- `spawn()` accepts `model: str | None` parameter to override default model
- `_run_subagent()` passes model to `AgentRunSpec`

### Completion Event Flow
```python
# SubagentStatus
completion_event: asyncio.Event  # set() when done

# wait_for_subagent
await status.completion_event.wait()
return status
```

---

## 4. Chained Trigger Execution

### Same-Turn Trigger Chaining

**bot/nanobot/agent/loop.py**
- `_spawn_counter_subagent()` passes `model=trigger.target.model` to `spawn()`
- Uses `_schedule_background(_chain_dependent_triggers(...))` for non-blocking chain execution
- `_chain_dependent_triggers()` awaits `subagent_manager.wait_for_subagent(task_id)` then spawns dependent triggers

### New Triggers

**`progress_tracker`** — fires when `user_responses.jsonl` has ≥2 new lines
- Uses `gpt-4o-mini` model
- Analyzes user responses, extracts language highlights

**`progress_organizer`** — fires only via `depends_on: progress_tracker` (never on its own)
- Uses `gpt-4o-mini` model
- Refines and merges highlights from `progress_bank.jsonl` into `progress.json`

---

## 5. Engineering Optimizations — Content-Only LLM Input

### Problem
Previously, LLM read `user_responses.jsonl` directly and saw all metadata fields (`session_uuid`, `round`, `topic`, `content`, `timestamp`). It only needed `content`, wasting tokens.

### Solution
Engineering layer extracts `content` before LLM call. LLM receives only content strings. After LLM returns highlights, engineering layer zips results with original `meta_info` using positional alignment.

### Data Flow
```
user_responses.jsonl
  └─> [Engineering: extract content] ──> LLM receives only content strings
       └─> [Engineering: zip with meta] ──> progress_bank.jsonl ({category, intent, expression, content, meta})

progress_bank.jsonl
  └─> [Engineering: extract expression+content] ──> LLM refines expressions only
       └─> [Engineering: zip with content+meta] ──> progress.json
```

### New Entry Formats

**progress_bank.jsonl:**
```json
{
  "category": "emotion",
  "intent": "preference",
  "expression": "be fond of",
  "content": "I'm really fond of collecting vintage sneakers",
  "meta": {
    "session_uuid": "...",
    "round": 4,
    "topic": "hobbies",
    "timestamp": "2026-05-21T..."
  }
}
```

**progress.json** (under categories):
```json
{
  "expression": "be fond of",
  "content": "I'm really fond of collecting vintage sneakers",
  "meta": {
    "session_uuid": "...",
    "round": 4,
    "topic": "hobbies",
    "timestamp": "2026-05-21T..."
  }
}
```

### Files Changed

**bot/nanobot/agent/tools/progress_bank.py**
- Added `contents: list[str]` parameter — content strings extracted by engineering
- `execute()` zips `contents[i]` with `entries[i]` and source `meta`

**bot/nanobot/agent/tools/progress_organizer.py**
- Added `contents: list[str]` parameter — expression strings for refinement
- Reads full entries from `progress_bank.jsonl` to preserve `content` + `meta`

**persona/subagents/cross_session/progress_tracker_subagent.md**
- LLM receives `contents` via tool call — no file reading
- Passes back same `contents` array for engineering alignment

**persona/subagents/cross_session/progress_organizer_subagent.md**
- LLM receives `contents` (expressions) via tool call — no file reading

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/agent/subagent.py | +completion_event, +wait_for_subagent, +model param, returns task_id |
| bot/nanobot/agent/loop.py | chained triggers via _schedule_background, model override pass-through |
| bot/nanobot/counter/types.py | +depends_on, +model fields, unified count |
| bot/nanobot/counter/engine.py | trigger chaining support |
| bot/nanobot/agent/tools/progress_bank.py | +contents param, new entry format with content+meta |
| bot/nanobot/agent/tools/progress_organizer.py | +contents param, preserve content+meta |
| persona/counter/triggers.yaml | new paths, +progress_tracker, +progress_organizer |
| persona/subagents/session/ | new dir — vocab, polisher, memory subagents |
| persona/subagents/cross_session/ | new dir — progress_tracker, progress_organizer subagents |

---

*Update created: 2026-05-21*

## 2026-05-20 - Session Persistence: UUID, Round Tracking, and Session Index

This update adds session UUID tracking, round tracking in messages (for indexing word/expression to original sentences), and a session index file for fast lookup.

---

## 1. Session UUID and Round Tracking

### Backend Changes

**bot/nanobot/session/manager.py**
- Added `uuid` import
- Added `_current_round: int = 0` field to `Session` dataclass (internal counter, not persisted)
- Added `session_uuid` field to `Session` dataclass (stored in metadata)
- Modified `get_or_create()` to generate UUID on session creation:
  - Creates `session_uuid = str(uuid.uuid4())`
  - Stores in `session.metadata["session_uuid"]`
  - Calls `_update_session_index(session)` to update index
- Modified `_load()` to extract `session_uuid` from metadata

### Session Index Management

**bot/nanobot/session/manager.py**
- Added `_index_path` property returning `sessions_dir.parent / "session_index.jsonl"`
- Added `_load_session_index()` - loads index from JSONL file, returns list of entries
- Added `_save_session_index(index)` - atomically writes index to JSONL file
- Added `_update_session_index(session)` - updates or creates index entry with:
  - `session_uuid`: unique identifier
  - `path`: session directory path
  - `topic`: session topic/name
  - `created_at`: ISO timestamp
  - `updated_at`: ISO timestamp
  - `total_rounds`: cumulative round count

### Round Tracking in Messages

**bot/nanobot/agent/loop.py**
- Modified `_save_turn()` to track rounds:
  - Initializes `current_round = session._current_round`
  - Determines `prev_role` from last saved message (if any)
  - On role switch (user↔assistant), increments `current_round`
  - Adds `"round": current_round` field to each message entry
  - Persists `session._current_round = current_round` after loop

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/session/manager.py | +45 lines: UUID, round field, session index management |
| bot/nanobot/agent/loop.py | +18 lines: round tracking in _save_turn |

---

## 2. Cross-Session User Expressions Log

### Purpose
Global `user_expressions.jsonl` file that collects all user responses across sessions for later processing by a subagent (to be implemented).

### File Location
`sessions/user_expressions.jsonl` (alongside `session_index.jsonl`)

### Entry Format
```json
{"session_uuid": "...", "round": 1, "topic": "...", "content": "...", "timestamp": "..."}
```

### Backend Changes

**bot/nanobot/session/manager.py**
- Added `_user_expressions_path` property returning `sessions_dir.parent / "user_expressions.jsonl"`
- Added `append_user_expression(session, round_num, content, topic)` method that appends a JSON line to the file

**bot/nanobot/agent/loop.py**
- Modified `_save_turn()` to call `self.sessions.append_user_expression()` when processing user messages

---

## 3. Progress Tracker Subagent

### Purpose
Analyze user expressions in batches to extract meaningful language highlights (phrases, collocations, expressions) and store them in `progress_bank.jsonl` for tracking expression breadth and improvement over time.

### Data Flow
```
user_expressions.jsonl (20 entries)
    ↓
progress_tracker subagent triggered (file_line_count condition)
    ↓
LLM: analyze 20 expressions → returns Array[20] of highlight arrays
    ↓
save_progress_entries tool: zip with source info, write to progress_bank.jsonl
    ↓
Clear user_expressions.jsonl
```

### New Condition Kind: file_line_count

**bot/nanobot/counter/types.py**
- Added `file_line_count` to `CounterCondition.kind`
- Added `path` and `threshold` fields for file-based condition

**bot/nanobot/counter/engine.py**
- Added `file_line_count` handling in `check_triggers()`
- Added `_fired_file_triggers` set to prevent re-firing until file is cleared
- Added `reset_file_trigger()` method

### New Tool: save_progress_entries

**bot/nanobot/agent/tools/progress_bank.py** (new file)
- `ProgressBankTool` with `save_progress_entries` function
- Schema: `entries: Array[Array[{category, intent, expression}]]`
- Reads source info from `user_expressions.jsonl` (positional alignment)
- Writes flat entries to `progress_bank.jsonl` with source info attached
- Clears `user_expressions.jsonl` after successful write

### Progress Bank Format

**progress_bank.jsonl** entries:
```json
{"category":"emotion","intent":"preference","expression":"be fond of","session_uuid":"...","round":4,"topic":"basketball"}
```

### Trigger Configuration

**persona/counter/triggers.yaml**
- Added `progress_tracker` trigger:
  - `kind: file_line_count`
  - `path: sessions/user_expressions.jsonl`
  - `threshold: 20`

### Subagent Prompt

**persona/subagents/progress_tracker_subagent.md** (new file)
- Reads `user_expressions.jsonl`
- LLM outputs `save_progress_entries` with nested array format
- Category taxonomy: emotion, description, experience, habit, opinion, goal, comparison, cause
- Intent tags: positive, negative, preference, habit, frequency, reason, etc.
- Positional alignment: `entries[i]` corresponds to line i of input file

---

## 2026-05-20 - Counter Engine, Subagent Status Notifications, and Session Path Fix

This update introduces a configurable counter-based trigger system for subagents, WebSocket notifications for subagent status, fixes session directory lookup for renamed sessions, and updates user memory profile.

---

## 1. Counter Engine (Configurable Subagent Triggers)

### New Files

**bot/nanobot/counter/** (new package)
- `__init__.py` - Package init
- `types.py` - Dataclasses for `CounterTrigger`, `CounterCondition`, `CounterTarget`
- `engine.py` - `CounterEngine` class that loads triggers from YAML and evaluates conditions

**persona/counter/triggers.yaml** (new file)
- YAML configuration for count-based trigger system
- Three default triggers:
  - `vocab_analysis`: every 2 turns, silent
  - `polish_feedback`: every 3 turns, silent
  - `memory_update`: every 10 turns, silent

### Backend Changes

**bot/nanobot/agent/loop.py**
- Replaced hardcoded `_spawn_session_subagents()` with `CounterEngine`-based approach
- `_spawn_counter_subagent()` spawns a single subagent from a counter trigger
- `counter_engine: CounterEngine` initialized in `__init__`
- `_maybe_spawn_periodic_subagents()` now uses `counter_engine.check_triggers()` instead of hardcoded interval
- Added `_on_subagent_status_change()` callback that broadcasts subagent status via message bus
- Added `on_status_change` parameter to `SubagentManager.__init__`

**bot/nanobot/agent/subagent.py**
- Added `on_status_change` callback to notify when subagents start/complete/fail
- Fires callback on task start and in `finally` block on completion/error

---

## 2. Subagent Status Notifications via WebSocket

### Backend

**bot/nanobot/channels/websocket.py**
- Added `send_subagent_status()` method to broadcast subagent status events
- Handles `_subagent_status` metadata and forwards to `send_subagent_status()`
- Sends `subagent_status` event with: `task_id`, `label`, `phase` (started/done/error), `error`

### Frontend

**bot/webui/src/lib/types.ts**
- Added `subagent_status` event type to `InboundEvent`

**bot/webui/src/lib/nanobot-client.ts**
- Added `onSubagentStatus()` handler registration
- Routes `subagent_status` events to registered handlers

**bot/webui/src/App.tsx**
- Added `subagentToasts` state to display subagent status notifications
- `useEffect` subscribes to `client.onSubagentStatus()` events
- Shows toast notifications: "vocab subagent running...", "vocab subagent completed", etc.
- Toasts auto-dismiss after 3 seconds
- Styled with color-coded borders: blue (started), green (done), red (error)

---

## 3. Session Directory Path Fix

**bot/nanobot/session/manager.py**
- Fixed `_get_session_dir()` to handle renamed sessions:
  - First tries cached metadata for custom folder name
  - Then tries expected path via `safe_key(key)`
  - Falls back to scanning all session directories to find matching key in metadata
- Added `_find_session_dir_by_key()` helper method for directory search
- This fixes the issue where clicking a renamed session (e.g., "Collecting") would create a new blank session

---

## 4. User Memory Updates

**persona/memory/MEMORY.md**
- Updated Music section with user's actual preferences:
  - Likes "We Believe" (anthemic track)
  - Fan of David Tao (陶喆) - Mandopop/R&B artist
  - Vocabulary notes: casual language, needs descriptive alternatives
  - Grammar notes: lowercase "i", filler "emm", short sentences
- Updated IELTS-Specific Patterns:
  - Vocabulary Gaps: "like" alternatives, casual slang upgrades
  - Grammar Issues: capitalization, fillers, sentence variety, run-on sentences, articles

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/agent/loop.py | +162/-99 lines: CounterEngine integration, status callbacks |
| bot/nanobot/agent/subagent.py | +8 lines: on_status_change callback |
| bot/nanobot/channels/websocket.py | +36 lines: send_subagent_status |
| bot/nanobot/session/manager.py | +36 lines: session directory fallback search |
| bot/nanobot/counter/ | new package: types.py, engine.py |
| bot/webui/src/App.tsx | +47 lines: subagent toast notifications |
| bot/webui/src/lib/nanobot-client.ts | +16 lines: onSubagentStatus handler |
| bot/webui/src/lib/types.ts | +8 lines: subagent_status event type |
| persona/counter/triggers.yaml | new file: counter trigger configuration |
| persona/memory/MEMORY.md | updated: user preferences and IELTS patterns |

---

*Update created: 2026-05-20*

This update adds Free Chat button to web UI, implements cross-session memory tracking, refactors subagent system for silent file-only output, and redesigns the topic bank.

---

## Architecture Flowchart

### 1. Free Chat Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FREE CHAT FLOW                                  │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────────────┐
  │  Web UI      │      │  Backend     │      │  Topic Selection             │
  │  Sidebar     │      │  /freechat   │      │  (cmd_freechat)              │
  └──────┬───────┘      └──────┬───────┘      └──────────┬───────────────────┘
         │                      │                           │
         │  Click "Free Chat"   │                           │
         │  ─────────────────►  │                           │
         │                      │   Parse topic_bank.md      │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Read profile for         │
         │                      │   exploration status       │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Select topic:            │
         │                      │   Priority:                │
         │                      │   1. not_explored          │
         │                      │   2. in_progress (depth<4) │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Choose question by       │
         │                      │   depth level              │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Rename session folder    │
         │                      │   to topic name            │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Return intro_prompt       │
         │                      │   to LLM                   │
         │◄─────────────────────│                           │
         │                      │                           │
         │                      │   LLM asks first question  │
         │                      │   naturally                │
         ▼                      ▼                           ▼
```

### 2. Memory Update Flow (Session Change)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MEMORY UPDATE FLOW                                  │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────────────┐
  │  User        │      │  AgentLoop   │      │  Session Manager              │
  │  Action      │      │  _dispatch   │      │                                │
  └──────┬───────┘      └──────┬───────┘      └──────────┬───────────────────┘
         │                      │                           │
         │  Switch session      │                           │
         │  or close chat       │                           │
         │  ─────────────────►  │                           │
         │                      │   Detect session change    │
         │                      │   via _last_active_key    │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   _on_session_inactive()   │
         │                      │   - Check message count    │
         │                      │   - 5min cooldown check    │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Spawn memory subagent    │
         │                      │   (announce_result=False)   │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Read thread.jsonl        │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Update MEMORY.md        │
         │                      │   (cross-session profile)   │
         │                      │   ─────────────────────►   │
         │                      │                           │
         │                      │   Topics: Status, Depth,   │
         │                      │   Key Facts, Vocab,       │
         │                      │   Grammar                  │
         ▼                      ▼                           ▼
```

### 3. Subagent Periodic Spawning

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SUBAGENT SPAWNING FLOW                                │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐      ┌──────────────┐      ┌──────────────────────────────┐
  │  User        │      │  AgentLoop   │      │  Subagent Manager             │
  │  Message     │      │  _maybe_     │      │  (background)                │
  │              │      │  spawn_      │      │                                │
  └──────┬───────┘      │  periodic_   │      └──────────┬───────────────────┘
         │              │  subagents   │                 │
         │  Send msg    │◄─────────────│                 │
         │  ─────────►  │              │                 │
         │              │  Increment   │                 │
         │              │  msg_count   │                 │
         │              │              │                 │
         │              │  Check:      │                 │
         │              │  - msg==1    │                 │
         │              │  - msg%3==0  │                 │
         │              │  - not /free │                 │
         │              │  chat        │                 │
         │              │  ─────────►  │                 │
         │              │              │   Spawn 3 subagents (silent):
         │              │              │   1. vocab
         │              │              │   2. polisher
         │              │              │   3. memory
         │              │              │   ──────────────►
         │              │              │                 │
         │              │              │   Read thread   │ ◄── thread.jsonl
         │              │              │   ──────────────►
         │              │              │                 │
         │              │              │   Write notes  │ ──► notes/vocab.md
         │              │              │   (silent)     │ ──► notes/polisher.md
         │              │              │                 │ ──► notes/profile.md
         │              │              │                 │
         │              │   UI does NOT wait             │
         │              │   (announce=False)             │
         ▼              ▼                                ▼
```

### 4. Session Directory Structure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        SESSION DIRECTORY STRUCTURE                          │
└─────────────────────────────────────────────────────────────────────────────┘

  sessions/
  │
  ├── basketball/                    # Session folder (auto-renamed to topic)
  │   ├── thread.jsonl               # Conversation history
  │   └── notes/
  │       ├── vocab.md               # Vocabulary suggestions
  │       ├── polisher.md            # Grammar improvements
  │       └── profile.md             # Session user profile
  │
  ├── daily_routine/
  │   ├── thread.jsonl
  │   └── notes/
  │       └── ...
  │
  └── ... (more sessions)

  persona/
  │
  └── memory/
      └── MEMORY.md                  # Cross-session user profile (updated on
                                     # session change, not per-session)
```

---

## 1. Free Chat Feature

### Web UI Changes

**bot/webui/src/App.tsx**
- Added `onFreeChat` callback that:
  - Creates a new chat via API
  - Sets active key to the new session
  - Sends `/freechat` command to trigger topic selection
- Button added to Sidebar component

**bot/webui/src/components/Sidebar.tsx**
- Added `onFreeChat` prop to SidebarProps interface
- Added "Free chat" button with Sparkles icon (lucide-react)
- Button styling: ghost variant, 8 height, full width, rounded-full

**bot/webui/src/i18n/locales/en/common.json**
- Added `"freeChat": "Free chat"` translation key

### Backend Command

**bot/nanobot/command/builtin.py**
- Added new BuiltinCommandSpec for `/freechat` with sparkles icon
- Implemented `cmd_freechat()` handler that:
  - Parses topic_bank.md for topics with depth levels and question types
  - Reads session profile to determine exploration status (not_explored, in_progress)
  - Selects priority: not_explored topics first, then in_progress with depth < 4
  - For new topics: starts with depth level 1 question (simple preference)
  - For continuing topics: progresses to next depth level
  - Sets session title and renames folder to topic name
  - Returns an intro prompt instructing the agent to ask the selected question naturally

---

## 2. Session Directory Structure

**bot/nanobot/session/manager.py**
- Sessions now stored in directories: `sessions/{safe_topic_name}/`
- Each session directory contains:
  - `thread.jsonl` - conversation history
  - `notes/vocab.md` - per-session vocabulary notes
  - `notes/polisher.md` - per-session grammar notes
  - `notes/profile.md` - per-session user profile

**New Methods:**
- `_get_session_dir(key)` - returns Path to session directory, checks metadata for custom folder name
- `rename_session_dir(key, new_name)` - renames folder to topic-based name, stores mapping in metadata
- `_ensure_session_notes(key)` - creates notes directory with vocab.md, polisher.md, profile.md
- `get_session_notes(key)` - reads and returns vocab and polisher notes as dict
- `_migrate_legacy_session(legacy_path, new_dir)` - migrates flat .jsonl to directory structure

**Modified Methods:**
- `get_or_create(key)` - now calls `_ensure_session_notes()` to set up directory
- `delete_session(key)` - now deletes entire session directory (not just .jsonl file)
- `list_sessions()` - now iterates directories instead of .jsonl files

---

## 3. Subagent System Refactor

### Silent Operation (announce_result=False)

**bot/nanobot/agent/subagent.py**
- Added `announce_result: bool = True` field to SubagentStatus dataclass
- Modified `spawn()` to accept `extra_system_prompt` and `announce_result` parameters
- Modified `_run_subagent()` to conditionally call `_announce_result()` only when `announce_result=True`
- Added `get_announcing_count_by_session(session_key)` - counts only announcing subagents
- Modified `_build_subagent_prompt()` to append extra_system_prompt if provided

**bot/nanobot/agent/loop.py**
- Changed `_drain_pending` condition from `get_running_count_by_session` to `get_announcing_count_by_session`
  - This prevents UI from waiting for non-announcing (silent) subagents

### Periodic Subagent Spawning

**bot/nanobot/agent/loop.py**
- Added constants: `SUBAGENTS_SPAWNED_KEY`, `MESSAGE_COUNT_KEY`, `TITLE_KEY`, `SUBAGENTS_TRIGGER_INTERVAL = 3`
- Added `_spawn_session_subagents()` - spawns vocab, polisher, memory subagents with:
  - `announce_result=False` for silent operation
  - `extra_system_prompt` loaded from workspace subagent prompt files
  - Session directory and workspace path substitution in prompts
- Added `_maybe_spawn_periodic_subagents()` - spawns subagents:
  - On first message (current_count == 1)
  - Every 3 messages thereafter
  - Skips `/freechat` command (only real conversation triggers subagents)
- Added `_apply_session_title()` - generates title from first user message and renames session folder
- Added `_generate_session_title()` - extracts first 50 chars from first user message

### Session Title Auto-Generation

- Session folders now auto-renamed to topic-based titles
- Title generated from first user message content
- Uses `safe_filename()` to create filesystem-safe names

---

## 4. Memory System - Cross-Session User Profile

### User-Level Memory File

**persona/memory/MEMORY.md**
- Complete rewrite as cross-session user memory profile
- Organized by 7 topic_bank sections matching topic categories:
  - Section 1: Hobbies & Interests (Sport, Music, Collecting, Cooking)
  - Section 2: Daily Life & Lifestyle (Daily Routine, Weekend Activities, Work-Life Balance)
  - Section 3: Travel & Places (Travel Experience, Dream Destination, Hometown)
  - Section 4: People & Relationships (Family, Friendship, Person You Admire)
  - Section 5: Food & Culture (Food & Eating Habits, Local Culture)
  - Section 6: Learning & Growth (Education, Future Plans, Personal Growth)
  - Section 7: Opinions & Society (Social Issues, Values & Beliefs, Happiness & Success)

- Each topic tracks:
  - Status: not_explored | briefly_mentioned | well_explored
  - Depth Level: 1-5 (IELTS speaking depth)
  - Key Facts: user-provided information
  - Vocabulary Notes: words/phrases used
  - Grammar Patterns: observed patterns
  - Last Discussed: timestamp

- Global section includes:
  - Basic Info: MBTI, Energy Type, First Language, Target Score, Occupation
  - Personality Insights: Strengths, Areas for Improvement, Communication Style
  - IELTS-Specific Patterns: Vocabulary Gaps, Grammar Issues, Hesitation Topics, Confident Topics
  - Suggested Next Topics: for future sessions

### Memory Subagent Update

**persona/subagents/memory_subagent.md**
- Complete rewrite to write to `memory/MEMORY.md` instead of per-session notes
- Reads: topic_bank.md, thread.jsonl, memory_format.md
- Writes to: `{{ workspace }}/memory/MEMORY.md`
- Topic category mapping to 7 sections
- Depth assessment guidelines (1=simple preference, 5=philosophy/values)
- Updates exploration status and depth level for discussed topics

### Vocab Subagent Update

**persona/subagents/vocab_subagent.md**
- Updated to write vocabulary suggestions to `memory/MEMORY.md`
- Added IELTS-specific vocabulary improvement guidance
- Added professional vocabulary by topic category
- Added linking phrases and collocations

### Polisher Subagent Update

**persona/subagents/polisher_subagent.md**
- Updated to write grammar notes to `memory/MEMORY.md`
- Added grammar improvement focus areas:
  - Vocabulary (Lexical Resource): weak→strong, informal→formal
  - Grammar (Grammatical Range): simple→compound/complex, relative clauses, conditionals
  - Fluency & Coherence: linking phrases, discourse markers
  - Task Achievement: direct answers, developing ideas with examples

### Memory Format

**persona/formats/memory_format.md**
- New file with output format template for profile updates

---

## 5. Session Change Hook for Memory Updates

**bot/nanobot/agent/loop.py**
- Added `_last_active_session_key` tracking in `__init__`
- Added `_on_session_inactive(session_key)` method:
  - Triggered when user switches to a different session
  - Checks for minimum 2 messages (meaningful content)
  - 5-minute cooldown prevents excessive spawns
  - Spawns memory subagent to update user-level `memory/MEMORY.md`
- Added session switch detection in `_dispatch`:
  - Compares `_last_active_session_key` with `effective_key`
  - If different and new session not in `_pending_queues`, calls `_on_session_inactive()`
- After detection, updates `_last_active_session_key = effective_key`

---

## 6. Topic Bank Redesign

**persona/topic_bank.md**
- Complete rewrite in English
- Restructured with 7 sections matching memory categories
- Each topic now has:
  - Multiple questions with depth levels 1-5
  - Sub-topic tracking: reason, timeline, frequency, opinion, impact, comparison, etc.
  - Questions designed for IELTS speaking practice

**Depth Level Design:**
- Depth 1: Simple preference ("Do you like...?")
- Depth 2: Reason/timeline ("Why? When did you start?")
- Depth 3: Opinion/comparison ("What's your opinion? How does it compare to...?")
- Depth 4: Impact/analysis ("How has it affected your life?")
- Depth 5: Philosophy/values ("How would you be different without...? What does it mean to you?")

---

## 7. Session Notes in Context

**bot/nanobot/agent/context.py**
- Modified `build_system_prompt()` to accept `session_notes` parameter
- If session_notes provided, appends Vocabulary Notes and Polisher Notes sections
- Modified `build_messages()` to accept `session_notes` and `session_dir` parameters
- Appends "Session Notes Directory: {dir}/notes/" to runtime context

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/agent/loop.py | +224 lines: session title, periodic subagents, session change hook |
| bot/nanobot/agent/subagent.py | +55 lines: announce_result flag, get_announcing_count_by_session |
| bot/nanobot/command/builtin.py | +184 lines: /freechat command with topic selection |
| bot/nanobot/session/manager.py | +144 lines: directory structure, rename, legacy migration |
| bot/nanobot/agent/context.py | +14 lines: session_notes in context building |
| bot/webui/src/App.tsx | +15 lines: onFreeChat handler |
| bot/webui/src/components/Sidebar.tsx | +10 lines: Free Chat button |
| bot/webui/src/i18n/locales/en/common.json | +1 line: freeChat translation |
| persona/memory/MEMORY.md | +253 lines: complete rewrite as user-level cross-session memory |
| persona/topic_bank.md | complete rewrite in English with depth levels |
| persona/formats/memory_format.md | new file: memory output format template |
| persona/subagents/*.md | complete rewrites: memory, vocab, polisher subagents |

---

## 2026-05-20 - Session Notes Panel and Highlighting Syntax

This update adds a Session Notes Panel to the WebUI for viewing vocab/polisher notes, implements keyword highlighting syntax (`==word==`), and fixes session deduplication.

---

## 1. Session Notes Panel

### New Files

**bot/webui/src/components/SessionNotesSheet.tsx** (134 lines)
- Sheet component that slides in from the right
- Two tabs: Vocabulary and Grammar
- Polls for updates every 5 seconds
- Renders markdown content with MarkdownTextRenderer
- Displays session title in header

**bot/webui/src/hooks/useSessionNotes.ts** (68 lines)
- Fetches session notes via API
- 5-second polling interval when panel is open
- Returns `notes.vocab` and `notes.polisher` strings

### Backend API Endpoint

**bot/nanobot/channels/websocket.py**
- Added `GET /api/sessions/<key>/notes` handler (`_handle_session_notes`)
- Returns `{"vocab": "...", "polisher": "..."}`
- Validates session key and authorization

### Frontend Integration

**bot/webui/src/App.tsx**
- Added `notesSheetState` for managing sheet open/close
- Added `handleOpenNotes` callback
- Closes notes sheet when switching sessions

**bot/nanobot/session/manager.py**
- Added `_find_session_notes_dir(key)` fallback method:
  - Scans session directories for matching key in metadata
  - Handles renamed sessions that don't use safe_key paths
- Fixed `get_session_notes()` to use fallback search

**bot/webui/src/lib/api.ts**
- Added `fetchSessionNotes(token, key)` function
- Added `SessionNotes` interface: `{ vocab: string, polisher: string }`

---

## 2. Highlighting Syntax

### Markdown Rendering

**bot/webui/src/components/MarkdownTextRenderer.tsx**
- Complete rewrite of highlight handling
- Uses `remark-directive` plugin for directive parsing
- Custom `remarkHighlight()` plugin transforms `==word==` to textDirective nodes
- Sets `hName: "mark"` and `hProperties` for directive conversion
- `<mark>` elements render with amber background:
  - Light mode: `bg-amber-200 text-amber-900`
  - Dark mode: `dark:bg-amber-700/50 dark:text-amber-100`

### Subagent Output Format

**persona/subagents/vocab_subagent.md**
- Added highlighting syntax documentation
- Sample output uses `==word==` for key vocabulary

**persona/subagents/polisher_subagent.md**
- Added highlighting syntax documentation

### CSS

**bot/webui/src/globals.css**
- Added `.highlight` class (backup for simple highlighting)

---

## 3. Session Deduplication

### Backend

**bot/nanobot/session/manager.py**
- `list_sessions()` now deduplicates by key:
  - Keeps first occurrence (most recent)
  - Prevents duplicate sessions in sidebar

### Frontend

**bot/webui/src/hooks/useSessions.ts**
- `refresh()` now deduplicates sessions client-side
- Uses `Set` to track seen keys

---

## Summary of Files Changed

| File | Changes |
|------|---------|
| bot/nanobot/channels/websocket.py | +18 lines: session notes API endpoint |
| bot/nanobot/session/manager.py | +32 lines: fallback search, deduplication |
| bot/webui/src/App.tsx | +33 lines: notes sheet state management |
| bot/webui/src/components/MarkdownTextRenderer.tsx | +83 lines: highlight syntax support |
| bot/webui/src/components/SessionNotesSheet.tsx | new file (134 lines) |
| bot/webui/src/components/thread/ThreadHeader.tsx | +15 lines: BookOpen icon button |
| bot/webui/src/components/thread/ThreadShell.tsx | +3 lines: onOpenNotes prop |
| bot/webui/src/globals.css | +13 lines: highlight CSS class |
| bot/webui/src/hooks/useSessionNotes.ts | new file (68 lines) |
| bot/webui/src/hooks/useSessions.ts | +9 lines: deduplication |
| bot/webui/src/i18n/locales/en/common.json | +10 lines: notes.* translations |
| bot/webui/src/lib/api.ts | +16 lines: fetchSessionNotes |
| persona/subagents/vocab_subagent.md | +20 lines: highlighting syntax |
| persona/subagents/polisher_subagent.md | +31 lines: highlighting syntax |
| persona/sessions/Collecting/notes/*.md | updated: ==word== highlighting |

---

*Update created: 2026-05-20*
