# Update Log

## 2026-05-19 - Free Chat, Session Memory System, and Subagent Refactor

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
