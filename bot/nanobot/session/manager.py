"""Session management for conversation history."""

import json
import os
import re
import shutil
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir
from nanobot.utils.helpers import (
    ensure_dir,
    estimate_message_tokens,
    find_legal_message_start,
    image_placeholder_text,
    safe_filename,
)
from nanobot.utils.subagent_channel_display import scrub_subagent_announce_body

FILE_MAX_MESSAGES = 2000
_MESSAGE_TIME_PREFIX_RE = re.compile(r"^\[Message Time: [^\]]+\]\n?")
_LOCAL_IMAGE_BREADCRUMB_RE = re.compile(r"^\[image: (?:/|~)[^\]]+\]\s*$")
_TOOL_CALL_ECHO_RE = re.compile(r'^\s*(?:generate_image|message)\([^)]*\)\s*$')
_SESSION_PREVIEW_MAX_CHARS = 120


def _sanitize_assistant_replay_text(content: str) -> str:
    """Remove internal replay artifacts that the model may have copied before.

    These strings are useful as runtime/session metadata, but when they appear
    in assistant examples they become demonstrations for the model to repeat.
    """
    content = _MESSAGE_TIME_PREFIX_RE.sub("", content, count=1)
    lines = [
        line
        for line in content.splitlines()
        if not _LOCAL_IMAGE_BREADCRUMB_RE.match(line)
        and not _TOOL_CALL_ECHO_RE.match(line)
    ]
    return "\n".join(lines).strip()


def _text_preview(content: Any) -> str:
    """Return compact display text for session lists."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                value = block.get("text")
                if isinstance(value, str):
                    parts.append(value)
        text = " ".join(parts)
    else:
        return ""
    text = _sanitize_assistant_replay_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _SESSION_PREVIEW_MAX_CHARS:
        text = text[: _SESSION_PREVIEW_MAX_CHARS - 1].rstrip() + "…"
    return text


def _message_preview_text(message: dict[str, Any]) -> str:
    """Session list preview text; subagent inject blobs are shortened for display."""
    content: Any = message.get("content")
    if message.get("injected_event") == "subagent_result" and isinstance(content, str):
        content = scrub_subagent_announce_body(content)
    return _text_preview(content)


@dataclass
class Session:
    """A conversation session."""

    key: str  # channel:chat_id
    session_uuid: str = ""  # Unique identifier for this session
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files
    _current_round: int = 0  # Internal counter for round tracking (not persisted)

    @staticmethod
    def _annotate_message_time(message: dict[str, Any], content: Any) -> Any:
        """Expose persisted turn timestamps to the model for relative-date reasoning.

        Annotating *every* assistant turn trains the model (via in-context
        demonstrations) to start its own replies with the same
        ``[Message Time: ...]`` prefix, which leaks metadata back to the user.
        We therefore only annotate user turns. User-side stamps are enough to
        pin adjacent assistant replies for relative-time reasoning, including
        proactive messages the user replies to later.
        """
        timestamp = message.get("timestamp")
        if not timestamp or not isinstance(content, str):
            return content
        role = message.get("role")
        if role != "user":
            return content
        return f"[Message Time: {timestamp}]\n{content}"

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def _create_unified_interaction_record(
        self,
        message: dict[str, Any],
        message_index: int,
    ) -> dict[str, Any]:
        """Transform a session message into the unified interaction format."""
        content = message.get("content", "")

        if isinstance(content, str):
            content_type = "text"
            text_content = content
            audio_url = None
        elif isinstance(content, dict):
            content_type = content.get("type", "text")
            text_content = content.get("text", "")
            audio_url = content.get("audio_url")
        else:
            content_type = "text"
            text_content = str(content)
            audio_url = None

        return {
            "id": str(uuid.uuid4()),
            "timestamp": message.get("timestamp", datetime.now().isoformat()),
            "source": {
                "type": "session",
                "mode": self.metadata.get("mode", "freechat"),
                "session_uuid": self.session_uuid or None,
                "message_index": message_index,
            },
            "role": message.get("role", "assistant"),
            "content": {
                "type": content_type,
                "text": text_content,
                "audio_url": audio_url,
            },
            "metadata": {
                "topic": self.metadata.get("topic"),
                "intent": self.metadata.get("intent"),
                "channel": self.metadata.get("channel"),
                "languages": self.metadata.get("languages"),
            },
        }

    def get_history(
        self,
        max_messages: int = 120,
        *,
        max_tokens: int = 0,
        include_timestamps: bool = False,
    ) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input.

        History is sliced by message count first (``max_messages``), then by
        token budget from the tail (``max_tokens``) when provided.
        """
        unconsolidated = self.messages[self.last_consolidated:]
        max_messages = max_messages if max_messages > 0 else 120
        sliced = unconsolidated[-max_messages:]

        # Avoid starting mid-turn when possible, except for proactive
        # assistant deliveries that the user may be replying to.
        for i, message in enumerate(sliced):
            if message.get("role") == "user":
                start = i
                if i > 0 and sliced[i - 1].get("_channel_delivery"):
                    start = i - 1
                sliced = sliced[start:]
                break

        # Drop orphan tool results at the front.
        start = find_legal_message_start(sliced)
        if start:
            sliced = sliced[start:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            if message.get("_command"):
                continue
            content = message.get("content", "")
            role = message.get("role")
            if role == "assistant" and isinstance(content, str):
                content = _sanitize_assistant_replay_text(content)
            # Synthesize an ``[image: path]`` breadcrumb from the persisted
            # ``media`` kwarg so LLM replay still sees *something* where the
            # image used to be. Without this, an image-only user turn
            # replays as an empty user message — the assistant's reply then
            # looks like it's responding to nothing.
            media = message.get("media")
            if role == "user" and isinstance(media, list) and media and isinstance(content, str):
                breadcrumbs = "\n".join(
                    image_placeholder_text(p) for p in media if isinstance(p, str) and p
                )
                content = f"{content}\n{breadcrumbs}" if content else breadcrumbs
            if include_timestamps:
                content = self._annotate_message_time(message, content)
            if role == "assistant" and isinstance(content, str) and not content.strip():
                if not any(key in message for key in ("tool_calls", "reasoning_content", "thinking_blocks")):
                    continue
            entry: dict[str, Any] = {"role": message["role"], "content": content}
            for key in ("tool_calls", "tool_call_id", "name", "reasoning_content", "thinking_blocks"):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)

        if max_tokens > 0 and out:
            kept: list[dict[str, Any]] = []
            used = 0
            for message in reversed(out):
                tokens = estimate_message_tokens(message)
                if kept and used + tokens > max_tokens:
                    break
                kept.append(message)
                used += tokens
            kept.reverse()

            # Keep history aligned to the first visible user turn.
            first_user = next((i for i, m in enumerate(kept) if m.get("role") == "user"), None)
            if first_user is not None:
                kept = kept[first_user:]
            else:
                # Tight token budgets can otherwise leave assistant-only tails.
                # If a user turn exists in the unsliced output, recover the
                # nearest one even if it slightly exceeds the token budget.
                recovered_user = next(
                    (i for i in range(len(out) - 1, -1, -1) if out[i].get("role") == "user"),
                    None,
                )
                if recovered_user is not None:
                    kept = out[recovered_user:]

            # And keep a legal tool-call boundary at the front.
            start = find_legal_message_start(kept)
            if start:
                kept = kept[start:]
            out = kept
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()
        self.metadata.pop("_last_summary", None)

    def retain_recent_legal_suffix(self, max_messages: int) -> None:
        """Keep a legal recent suffix constrained by a hard message cap."""
        if max_messages <= 0:
            self.clear()
            return
        if len(self.messages) <= max_messages:
            return

        retained = list(self.messages[-max_messages:])

        # Prefer starting at a user turn when one exists within the tail.
        first_user = next((i for i, m in enumerate(retained) if m.get("role") == "user"), None)
        if first_user is not None:
            retained = retained[first_user:]
        else:
            # If the tail is assistant/tool-only, anchor to the latest user in
            # the full session and take a capped forward window from there.
            latest_user = next(
                (i for i in range(len(self.messages) - 1, -1, -1)
                 if self.messages[i].get("role") == "user"),
                None,
            )
            if latest_user is not None:
                retained = list(self.messages[latest_user: latest_user + max_messages])

        # Mirror get_history(): avoid persisting orphan tool results at the front.
        start = find_legal_message_start(retained)
        if start:
            retained = retained[start:]

        # Hard-cap guarantee: never keep more than max_messages.
        if len(retained) > max_messages:
            retained = retained[-max_messages:]
            start = find_legal_message_start(retained)
            if start:
                retained = retained[start:]

        dropped = len(self.messages) - len(retained)
        self.messages = retained
        self.last_consolidated = max(0, self.last_consolidated - dropped)
        self.updated_at = datetime.now()

    def enforce_file_cap(
        self,
        on_archive: Any = None,
        limit: int = FILE_MAX_MESSAGES,
    ) -> None:
        """Bound session message growth by archiving and trimming old prefixes."""
        if limit <= 0 or len(self.messages) <= limit:
            return

        before = list(self.messages)
        before_last_consolidated = self.last_consolidated
        before_count = len(before)
        self.retain_recent_legal_suffix(limit)
        dropped_count = before_count - len(self.messages)
        if dropped_count <= 0:
            return

        dropped = before[:dropped_count]
        already_consolidated = min(before_last_consolidated, dropped_count)
        archive_chunk = dropped[already_consolidated:]
        if archive_chunk and on_archive:
            on_archive(archive_chunk)
        logger.info(
            "Session file cap hit for {}: dropped {}, raw-archived {}, kept {}",
            self.key,
            dropped_count,
            len(archive_chunk),
            len(self.messages),
        )


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

    @staticmethod
    def safe_key(key: str) -> str:
        """Public helper used by HTTP handlers to map an arbitrary key to a stable filename stem."""
        return safe_filename(key.replace(":", "_"))

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session's thread.jsonl."""
        folder = self._get_session_dir(key)
        return folder / "thread.jsonl"

    def _get_session_dir(self, key: str) -> Path:
        """Get the directory path for a session.

        Checks session metadata for a custom folder name first.
        Falls back to searching through session directories if key doesn't match folder name.
        """
        import traceback
        # Log all callers with stack trace
        logger.debug(
            "_get_session_dir({}) called from:\n{}",
            key,
            "".join(traceback.format_stack()[-5:-1]),
        )

        # Try to get custom folder name from session metadata (if session is cached)
        if key in self._cache:
            session = self._cache[key]
            custom_folder = session.metadata.get("_session_folder")
            if custom_folder:
                result = self.sessions_dir / custom_folder
                logger.debug(
                    "_get_session_dir({}): cache hit, custom_folder={}, path={}",
                    key, custom_folder, result,
                )
                return result

        # Try the expected path first
        expected_path = self.sessions_dir / self.safe_key(key)
        if expected_path.exists():
            logger.debug("_get_session_dir({}): expected_path exists={}", key, expected_path)
            return expected_path

        # For websocket:{uuid} keys, try the UUID folder directly before fallback search
        if key.startswith("websocket:"):
            uuid_part = key[len("websocket:") :]
            uuid_path = self.sessions_dir / uuid_part
            if uuid_path.exists():
                logger.debug("_get_session_dir({}): found UUID folder={}", key, uuid_path)
                return uuid_path

        # Fallback: search through session directories to find the one with matching key
        found_dir = self._find_session_dir_by_key(key)
        if found_dir:
            logger.debug("_get_session_dir({}): found via fallback={}", key, found_dir)
            return found_dir

        # Return expected path even if it doesn't exist (will be created by caller)
        logger.debug("_get_session_dir({}): returning expected_path (does not exist yet)={}", key, expected_path)
        return expected_path

    def _find_session_dir_by_key(self, key: str) -> Path | None:
        """Find a session's directory by scanning for matching key in metadata."""
        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            thread_path = session_dir / "thread.jsonl"
            if not thread_path.exists():
                continue
            try:
                with open(thread_path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata" and data.get("key") == key:
                            return session_dir
            except Exception:
                continue
        return None

    def rename_session_dir(self, key: str, new_name: str) -> bool:
        """Rename a session's folder to a new name and store mapping in metadata.

        Returns True if renamed successfully.
        """
        # Use _get_session_dir which has fallback search logic
        old_dir = self._get_session_dir(key)
        if not old_dir.exists():
            logger.warning("rename_session_dir: old_dir does not exist: {}", old_dir)
            return False

        safe_name = safe_filename(new_name)
        if not safe_name:
            logger.warning("rename_session_dir: could not create safe filename from: {}", new_name)
            return False

        new_dir = self.sessions_dir / safe_name
        if new_dir.exists():
            suffix = 1
            while new_dir.exists():
                new_dir = self.sessions_dir / f"{safe_name}_{suffix}"
                suffix += 1

        try:
            old_dir.rename(new_dir)
            logger.info("Renamed session folder from {} to {}", old_dir.name, new_dir.name)

            # Update metadata with new folder name
            if key in self._cache:
                session = self._cache[key]
                session.metadata["_session_folder"] = new_dir.name
                # Save immediately so subsequent operations use new path
                self.save(session)

            return True
        except Exception as e:
            logger.warning("Failed to rename session folder: {}", e)
            return False

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.nanobot/sessions/)."""
        return self.legacy_sessions_dir / f"{self.safe_key(key)}.jsonl"

    def _ensure_session_notes(self, key: str) -> Path:
        """Ensure a session's notes directory exists and return its path.

        Creates notes/vocab.md and notes/polisher.md if they don't exist.
        """
        import traceback
        session_dir = self._get_session_dir(key)
        logger.info(
            "_ensure_session_notes({}): session_dir={}",
            key,
            session_dir,
        )
        logger.debug("  notes from:\n{}", "".join(traceback.format_stack()[-5:-1]))
        notes_dir = session_dir / "notes"
        ensure_dir(notes_dir)
        (notes_dir / "vocab.md").touch(exist_ok=True)
        (notes_dir / "polisher.md").touch(exist_ok=True)
        (notes_dir / "profile.md").touch(exist_ok=True)
        return notes_dir

    def get_session_notes(self, key: str) -> dict[str, str]:
        """Read vocab.md and polisher.md from a session's notes directory."""
        notes_dir = self._get_session_dir(key) / "notes"
        # Fallback: if notes_dir doesn't exist, search for the session by key in metadata
        if not notes_dir.exists():
            notes_dir = self._find_session_notes_dir(key) or notes_dir
        vocab = ""
        polisher = ""
        vocab_path = notes_dir / "vocab.md"
        polisher_path = notes_dir / "polisher.md"
        if vocab_path.exists():
            vocab = vocab_path.read_text(encoding="utf-8")
        if polisher_path.exists():
            polisher = polisher_path.read_text(encoding="utf-8")
        return {"vocab": vocab, "polisher": polisher}

    def _find_session_notes_dir(self, key: str) -> Path | None:
        """Find a session's notes directory by scanning for matching key in metadata."""
        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            thread_path = session_dir / "thread.jsonl"
            if not thread_path.exists():
                continue
            try:
                with open(thread_path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata" and data.get("key") == key:
                            return session_dir / "notes"
            except Exception:
                continue
        return None

    def _migrate_legacy_session(self, legacy_path: Path, new_dir: Path) -> None:
        """Migrate a legacy flat .jsonl session to the new directory structure."""
        try:
            ensure_dir(new_dir)
            new_path = new_dir / "thread.jsonl"
            if new_path.exists():
                logger.debug("New session already exists at {}, skipping legacy migration", new_path)
                return
            shutil.move(str(legacy_path), str(new_path))
            logger.info("Migrated session from {} to {}", legacy_path, new_path)
        except Exception:
            logger.exception("Failed to migrate session from {} to {}", legacy_path, new_dir)

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            # For websocket sessions, derive session_uuid from the key (websocket:{uuid})
            # This ensures the folder name matches the chatId known to the WebUI
            if key.startswith("websocket:"):
                session_uuid = key[len("websocket:") :]
            else:
                session_uuid = str(uuid.uuid4())
            session = Session(key=key, session_uuid=session_uuid)
            # Store session_uuid in metadata for persistence
            session.metadata["session_uuid"] = session.session_uuid
            # Use UUID as folder name (topic stored in metadata["title"] separately)
            session.metadata["_session_folder"] = session.session_uuid
        else:
            # Ensure _session_folder is set (for existing sessions loaded from disk)
            if "_session_folder" not in session.metadata:
                session.metadata["_session_folder"] = session.session_uuid
        # Cache BEFORE _ensure_session_notes so _get_session_dir can find the session metadata
        self._cache[key] = session
        self._ensure_session_notes(key)
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                self._migrate_legacy_session(legacy_path, self._get_session_dir(key))
            # Also check legacy flat format in sessions_dir
            legacy_flat = self.sessions_dir / f"{self.safe_key(key)}.jsonl"
            if legacy_flat.exists():
                self._migrate_legacy_session(legacy_flat, self._get_session_dir(key))

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            updated_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        updated_at = datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            session_uuid = metadata.get("session_uuid", "")
            if not session_uuid:
                session_uuid = str(uuid.uuid4())
                metadata["session_uuid"] = session_uuid
            # Ensure _session_folder is set (for existing sessions loaded from disk)
            if "_session_folder" not in metadata:
                metadata["_session_folder"] = session_uuid

            return Session(
                key=key,
                session_uuid=session_uuid,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            repaired = self._repair(key)
            if repaired is not None:
                logger.info("Recovered session {} from corrupt file ({} messages)", key, len(repaired.messages))
            return repaired

    def _repair(self, key: str) -> Session | None:
        """Attempt to recover a session from a corrupt JSONL file."""
        path = self._get_session_path(key)
        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: datetime | None = None
            updated_at: datetime | None = None
            last_consolidated = 0
            skipped = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        skipped += 1
                        continue

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        if data.get("created_at"):
                            with suppress(ValueError, TypeError):
                                created_at = datetime.fromisoformat(data["created_at"])
                        if data.get("updated_at"):
                            with suppress(ValueError, TypeError):
                                updated_at = datetime.fromisoformat(data["updated_at"])
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            if skipped:
                logger.warning("Skipped {} corrupt lines in session {}", skipped, key)

            if not messages and not metadata:
                return None

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Repair failed for session {}: {}", key, e)
            return None

    @staticmethod
    def _session_payload(session: Session) -> dict[str, Any]:
        return {
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "messages": session.messages,
        }

    def save(self, session: Session, *, fsync: bool = False) -> None:
        """Save a session to disk atomically.

        When *fsync* is ``True`` the final file and its parent directory are
        explicitly flushed to durable storage.  This is intentionally off by
        default (the OS page-cache is sufficient for normal operation) but
        should be enabled during graceful shutdown so that filesystems with
        write-back caching (e.g. rclone VFS, NFS, FUSE mounts) do not lose
        the most recent writes.
        """
        session_dir = self._get_session_dir(session.key)
        logger.info(
            "save({}): _session_folder={}, session_dir={}",
            session.key,
            session.metadata.get("_session_folder"),
            session_dir,
        )
        import traceback
        logger.debug("save() called from:\n{}", "".join(traceback.format_stack()))
        ensure_dir(session_dir)
        self._ensure_session_notes(session.key)
        path = self._get_session_path(session.key)
        tmp_path = path.with_suffix(".jsonl.tmp")

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                metadata_line = {
                    "_type": "metadata",
                    "key": session.key,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "metadata": session.metadata,
                    "last_consolidated": session.last_consolidated
                }
                f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
                for msg in session.messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                if fsync:
                    f.flush()
                    os.fsync(f.fileno())

            os.replace(tmp_path, path)

            # Also append to unified interaction log (best-effort)
            self._append_to_shared_interaction_log(session)

            if fsync:
                # fsync the directory so the rename is durable.
                # On Windows, opening a directory with O_RDONLY raises
                # PermissionError — skip the dir sync there (NTFS
                # journals metadata synchronously).
                with suppress(PermissionError):
                    fd = os.open(str(path.parent), os.O_RDONLY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

        self._cache[session.key] = session
        # Always update index on save so title changes are reflected
        self._update_session_index(session)

    def _append_to_shared_interaction_log(self, session: Session) -> None:
        """Append session messages to the unified thread.jsonl at data/ (best-effort)."""
        try:
            project_root = self.workspace.parent
            data_dir = project_root / "data"
            shared_path = data_dir / "thread.jsonl"
            tmp_path = shared_path.with_suffix(".jsonl.tmp")

            data_dir.mkdir(parents=True, exist_ok=True)

            existing_lines: list[str] = []
            if shared_path.exists():
                with open(shared_path, "r", encoding="utf-8") as f:
                    existing_lines = f.readlines()

            new_lines: list[str] = []
            for idx, msg in enumerate(session.messages):
                record = session._create_unified_interaction_record(msg, idx)
                new_lines.append(json.dumps(record, ensure_ascii=False) + "\n")

            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(existing_lines)
                f.writelines(new_lines)

            os.replace(tmp_path, shared_path)

            logger.debug(
                "Appended {} interactions to thread.jsonl for session {}",
                len(new_lines),
                session.key,
            )
        except Exception as exc:
            logger.warning(
                "Failed to append to thread.jsonl for session {}: {}",
                session.key,
                exc,
            )

    def flush_all(self) -> int:
        """Re-save every cached session with fsync for durable shutdown.

        Returns the number of sessions flushed.  Errors on individual
        sessions are logged but do not prevent other sessions from being
        flushed.
        """
        flushed = 0
        for key, session in list(self._cache.items()):
            try:
                self.save(session, fsync=True)
                flushed += 1
            except Exception:
                logger.warning("Failed to flush session {}", key, exc_info=True)
        return flushed

    # ─── Session Index ───────────────────────────────────────────────────────────

    @property
    def _index_path(self) -> Path:
        """Path to the session index file."""
        return self.sessions_dir.parent / "session_index.jsonl"

    def _load_session_index(self) -> list[dict[str, Any]]:
        """Load the session index from disk."""
        index_path = self._index_path
        if not index_path.exists():
            return []
        try:
            with open(index_path, encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except Exception:
            logger.warning("Failed to load session index from {}", index_path)
            return []

    def _save_session_index(self, index: list[dict[str, Any]]) -> None:
        """Save the session index to disk."""
        index_path = self._index_path
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                for entry in index:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            logger.warning("Failed to save session index to {}", index_path)

    def _update_session_index(self, session: Session) -> None:
        """Update the session index entry for a session."""
        if not session.session_uuid:
            return  # Skip if no session_uuid

        index = self._load_session_index()

        # Find existing entry by session_uuid
        entry_idx = None
        for i, entry in enumerate(index):
            if entry.get("session_uuid") == session.session_uuid:
                entry_idx = i
                break

        # Build entry
        # title is set by freechat command (the topic); _session_folder is the UUID folder name
        topic = session.metadata.get("title", "") or session.metadata.get("_session_folder", "")
        logger.debug(
            "_update_session_index: session_uuid={}, title={}, _session_folder={}, topic={}",
            session.session_uuid,
            session.metadata.get("title", ""),
            session.metadata.get("_session_folder", ""),
            topic,
        )
        session_dir = self._get_session_dir(session.key)
        relative_path = str(session_dir.relative_to(self.sessions_dir.parent))

        # Count rounds from messages
        rounds = 0
        if session.messages:
            rounds = session.messages[-1].get("round", 0)

        entry = {
            "session_uuid": session.session_uuid,
            "path": relative_path,
            "topic": topic,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "total_rounds": rounds,
        }

        if entry_idx is not None:
            index[entry_idx] = entry
        else:
            index.append(entry)

        self._save_session_index(index)

    # ─── User Expressions (Cross-Session) ────────────────────────────────────────

    @property
    def _responses_path(self) -> Path:
        """Path to the user responses file (cross-session)."""
        return self.sessions_dir.parent / "user_responses.jsonl"

    def append_user_expression(
        self,
        session: Session,
        round_num: int,
        content: str,
        topic: str = "",
    ) -> None:
        """Append a user expression to the cross-session expressions file."""
        logger.info(
            "append_user_expression CALLED: key={}, session_uuid={}, metadata={}",
            session.key,
            session.session_uuid,
            session.metadata,
        )
        session_uuid = session.session_uuid or session.metadata.get("session_uuid", "")
        if not session_uuid:
            logger.warning(
                "append_user_expression: no session_uuid for key={}, metadata={}",
                session.key,
                session.metadata,
            )
            return
        entry = {
            "session_uuid": session_uuid,
            "round": round_num,
            "topic": topic or session.metadata.get("_session_folder", ""),
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            with open(self._responses_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.info(
                "append_user_expression: wrote to {}, session_uuid={}, round={}, content_len={}",
                self._responses_path,
                session_uuid,
                round_num,
                len(content),
            )
        except Exception:
            logger.warning("Failed to append user expression to {}", self._responses_path)

    def _get_mode_responses_path(self, session: Session) -> Path | None:
        """Get mode-specific responses path based on session mode.

        Returns None if mode doesn't have a specific responses file.
        """
        session_uuid = session.session_uuid or session.metadata.get("session_uuid", "")
        if not session_uuid:
            return None

        mode = session.metadata.get("mode")
        if not mode:
            return None

        return self.sessions_dir.parent / mode / "sessions" / session_uuid / "responses.jsonl"

    def append_mode_response(
        self,
        session: Session,
        round_num: int,
        **fields: Any,
    ) -> None:
        """Append a mode-specific response to the mode-specific responses file.

        Generic method that works for any mode. The responses are stored under
        shared/{mode}/sessions/{session_uuid}/responses.jsonl.

        Args:
            session: The current session.
            round_num: Conversation round number.
            **fields: Mode-specific data fields (e.g., zh, user_en for benative;
                      topic, content for freechat).
        """
        session_uuid = session.session_uuid or session.metadata.get("session_uuid", "")
        if not session_uuid:
            logger.warning("append_mode_response: no session_uuid")
            return

        mode = session.metadata.get("mode")
        if not mode:
            logger.warning("append_mode_response: no mode set in session")
            return

        entry: dict[str, Any] = {
            "session_uuid": session_uuid,
            "round": round_num,
            "mode": mode,
            "timestamp": datetime.now().isoformat(),
        }
        entry.update(fields)

        responses_path = self._get_mode_responses_path(session)
        if not responses_path:
            logger.warning("append_mode_response: no mode-specific path for mode={}", mode)
            return

        try:
            ensure_dir(responses_path.parent)
            with open(responses_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logger.info(
                "append_mode_response: mode={}, path={}, session_uuid={}, round={}",
                mode,
                responses_path,
                session_uuid,
                round_num,
            )
        except Exception:
            logger.warning("Failed to append mode response to {}", responses_path)

    def append_benative_response(
        self,
        session: Session,
        round_num: int,
        article_id: str,
        zh: str,
        user_en: str,
    ) -> None:
        """[Deprecated] Use append_mode_response instead."""
        self.append_mode_response(
            session, round_num,
            article_id=article_id, zh=zh, user_en=user_en,
        )

    def append_freechat_response(
        self,
        session: Session,
        round_num: int,
        topic: str,
        content: str,
    ) -> None:
        """[Deprecated] Use append_mode_response instead."""
        self.append_mode_response(
            session, round_num,
            topic=topic or session.metadata.get("_session_folder", ""),
            content=content,
        )

    # ─── Progress Bank ─────────────────────────────────────────────────────────────

    @property
    def _progress_bank_path(self) -> Path:
        """Path to the progress bank file (cross-session user highlights)."""
        return self.sessions_dir.parent / "progress_bank.jsonl"

    def append_progress_entry(self, entry: dict) -> int:
        """Append a single progress entry to the progress bank.

        Returns the number of entries written (1).
        """
        try:
            with open(self._progress_bank_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return 1
        except Exception:
            logger.warning("Failed to append progress entry to {}", self._progress_bank_path)
            return 0

    def append_progress_entries(self, entries: list[dict]) -> int:
        """Append multiple progress entries to the progress bank.

        Returns the number of entries written.
        """
        if not entries:
            return 0
        try:
            with open(self._progress_bank_path, "a", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return len(entries)
        except Exception:
            logger.warning("Failed to append {} progress entries to {}", len(entries), self._progress_bank_path)
            return 0

    def clear_responses(self) -> bool:
        """Clear the user expressions file.

        Returns True if the file was deleted or didn't exist.
        """
        path = self._responses_path
        if not path.exists():
            return True
        try:
            path.unlink()
            return True
        except Exception:
            logger.warning("Failed to clear user expressions at {}", path)
            return False

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    def delete_session(self, key: str) -> bool:
        """Remove a session from disk and the in-memory cache.

        Returns True if the session directory was found and removed.
        """
        session_dir = self._get_session_dir(key)
        self.invalidate(key)
        if not session_dir.exists():
            return False
        try:
            shutil.rmtree(session_dir)
            return True
        except OSError as e:
            logger.warning("Failed to delete session directory {}: {}", session_dir, e)
            return False

    def read_session_file(self, key: str) -> dict[str, Any] | None:
        """Load a session from disk without caching; intended for read-only HTTP endpoints.

        Returns ``{"key", "created_at", "updated_at", "metadata", "messages"}`` or
        ``None`` when the session file does not exist or fails to parse.
        """
        path = self._get_session_path(key)
        if not path.exists():
            return None
        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: str | None = None
            updated_at: str | None = None
            stored_key: str | None = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = data.get("created_at")
                        updated_at = data.get("updated_at")
                        stored_key = data.get("key")
                    else:
                        messages.append(data)
            return {
                "key": stored_key or key,
                "created_at": created_at,
                "updated_at": updated_at,
                "metadata": metadata,
                "messages": messages,
            }
        except Exception as e:
            logger.warning("Failed to read session {}: {}", key, e)
            repaired = self._repair(key)
            if repaired is not None:
                logger.info("Recovered read-only session view {} from corrupt file", key)
                return self._session_payload(repaired)
            return None

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.

        Returns:
            List of session info dicts.
        """
        sessions = []

        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue
            thread_path = session_dir / "thread.jsonl"
            if not thread_path.exists():
                # Also check legacy flat .jsonl format for migration
                legacy = self.sessions_dir / f"{session_dir.name}.jsonl"
                if legacy.exists():
                    self._migrate_legacy_session(legacy, session_dir)
                    thread_path = session_dir / "thread.jsonl"
                if not thread_path.exists():
                    continue

            fallback_key = session_dir.name.replace("_", ":", 1)
            try:
                # Read the metadata line and a small preview for WebUI/session lists.
                with open(thread_path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or fallback_key
                            metadata = data.get("metadata", {})
                            title = metadata.get("title") if isinstance(metadata, dict) else None
                            preview = ""
                            fallback_preview = ""
                            for line in f:
                                if not line.strip():
                                    continue
                                item = json.loads(line)
                                if item.get("_type") == "metadata":
                                    continue
                                text = _message_preview_text(item)
                                if not text:
                                    continue
                                if item.get("role") == "user":
                                    preview = text
                                    break
                                if not fallback_preview and item.get("role") == "assistant":
                                    fallback_preview = text
                            preview = preview or fallback_preview
                            sessions.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "title": title if isinstance(title, str) else "",
                                "preview": preview,
                                "path": str(thread_path)
                            })
            except Exception:
                repaired = self._repair(fallback_key)
                if repaired is not None:
                    sessions.append({
                        "key": repaired.key,
                        "created_at": repaired.created_at.isoformat(),
                        "updated_at": repaired.updated_at.isoformat(),
                        "title": (
                            repaired.metadata.get("title")
                            if isinstance(repaired.metadata.get("title"), str)
                            else ""
                        ),
                        "preview": next(
                            (
                                text
                                for msg in repaired.messages
                                if (text := _message_preview_text(msg))
                            ),
                            "",
                        ),
                        "path": str(thread_path)
                    })
                continue

        # Deduplicate by key, keeping the first occurrence (most recent)
        seen = set()
        unique_sessions = []
        for s in sessions:
            if s["key"] not in seen:
                seen.add(s["key"])
                unique_sessions.append(s)

        return sorted(unique_sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
