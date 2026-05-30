"""Counter engine: evaluates count-based trigger conditions per session."""

import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.counter.types import CounterTrigger, CounterCondition, CounterTarget


_TURN_COUNT_KEY = "_counter_turn_count"
_LAST_TRIGGER_KEY_PREFIX = "_counter_last_trigger_"


def _resolve_trigger_workspace(workspace: Path) -> Path:
    """Return the root that owns mode/ and subagent/ runtime config.

    Some installs keep the nanobot data workspace at project_root/persona while
    prompts and trigger config live one directory up. Support that layout
    without forcing callers to change their configured data workspace.
    """
    workspace = Path(workspace)
    has_runtime_config = (
        (workspace / "mode" / "default" / "trigger" / "triggers.json").exists()
        or (workspace / "subagent").exists()
    )
    if has_runtime_config:
        return workspace
    parent = workspace.parent
    parent_has_runtime_config = (
        (parent / "mode" / "default" / "trigger" / "triggers.json").exists()
        or (parent / "subagent").exists()
    )
    if workspace.name == "persona" and parent_has_runtime_config:
        return parent
    return workspace


class CounterEngine:
    """Loads trigger config and evaluates which triggers should fire.

    Triggers are loaded from mode directories:
    - mode/default/trigger/triggers.json (always loaded)
    - mode/{current_mode}/trigger/triggers.json (loaded when in that mode)

    Each triggers.json contains the trigger config and cursor state.
    """

    def __init__(self, workspace: Path) -> None:
        self.data_workspace = Path(workspace)
        self.workspace = _resolve_trigger_workspace(self.data_workspace)
        self._triggers: list[CounterTrigger] = []
        self._current_mode: str | None = None
        self._default_triggers_file = self.workspace / "mode" / "default" / "trigger" / "triggers.json"
        self._mode_triggers_file: Path | None = None
        self._trigger_file_mtimes: dict[Path, int] = {}
        self._load_default_triggers()

    def _load_default_triggers(self) -> None:
        """Load default mode triggers (always loaded)."""
        if self._default_triggers_file.exists():
            self._load_triggers_file(self._default_triggers_file)
            logger.debug("Loaded default triggers from {}", self._default_triggers_file)

    def _load_mode_triggers(self, mode: str) -> None:
        """Load mode-specific triggers."""
        # Remove existing mode-specific triggers
        self._triggers = [t for t in self._triggers if self._default_triggers_file == t._triggers_file]
        self._mode_triggers_file = self.workspace / "mode" / mode / "trigger" / "triggers.json"
        if self._mode_triggers_file.exists():
            self._load_triggers_file(self._mode_triggers_file)
            logger.debug("Loaded mode-specific triggers from {}", self._mode_triggers_file)

    def _load_triggers_file(self, triggers_file: Path) -> None:
        """Load triggers from a single triggers.json file."""
        try:
            raw = json.loads(triggers_file.read_text(encoding="utf-8"))
            if not raw or not isinstance(raw, dict):
                return

            version = raw.get("version", 1)
            triggers_raw = raw.get("triggers", [])

            for t in triggers_raw:
                if not isinstance(t, dict):
                    continue

                # Build trigger with cursor from JSON
                condition = CounterCondition(**t.get("condition", {}))
                target = CounterTarget(**t.get("target", {}))
                cursor = t.get("cursor", {})

                trigger = CounterTrigger(
                    id=t["id"],
                    name=t.get("name", t["id"]),
                    enabled=t.get("enabled", True),
                    condition=condition,
                    target=target,
                    _cursor=cursor,  # Store cursor in trigger
                    _triggers_file=triggers_file,  # Store file path for writing
                )
                self._triggers.append(trigger)

            self._trigger_file_mtimes[triggers_file] = triggers_file.stat().st_mtime_ns
            logger.debug("Loaded {} trigger(s) from {}", len(triggers_raw), triggers_file)
        except Exception:
            logger.exception("Failed to load triggers from {}", triggers_file)

    def set_mode(self, mode: str | None) -> None:
        """Switch to a different mode, reloading triggers."""
        self._current_mode = mode
        self._load_mode_triggers(mode)
        enabled = [t for t in self._triggers if t.enabled]
        logger.info(
            "CounterEngine mode changed to '{}', loaded {} trigger(s) ({} enabled)",
            mode,
            len(self._triggers),
            len(enabled),
        )

    def ensure_mode(self, mode: str | None) -> None:
        """Ensure mode-specific triggers are loaded for the active session."""
        if mode == self._current_mode:
            return
        self.set_mode(mode)

    def reload_triggers(self) -> None:
        """Reload trigger files for the current mode."""
        self._triggers = []
        self._trigger_file_mtimes = {}
        self._load_default_triggers()
        if self._current_mode:
            self._load_mode_triggers(self._current_mode)

    def reload_if_changed(self) -> None:
        """Reload trigger config when a loaded trigger file changed on disk."""
        files = [self._default_triggers_file]
        if self._mode_triggers_file is not None:
            files.append(self._mode_triggers_file)
        for path in files:
            if not path.exists():
                continue
            mtime = path.stat().st_mtime_ns
            if self._trigger_file_mtimes.get(path) != mtime:
                self.reload_triggers()
                return

    def increment_turn(self, session_metadata: dict[str, Any]) -> int:
        """Bump the per-session turn counter and return the new count."""
        count = session_metadata.get(_TURN_COUNT_KEY, 0) + 1
        session_metadata[_TURN_COUNT_KEY] = count
        return count

    def get_turn_count(self, session_metadata: dict[str, Any]) -> int:
        """Return the current turn count for a session."""
        return session_metadata.get(_TURN_COUNT_KEY, 0)

    def check_triggers(self, session_metadata: dict[str, Any]) -> list[CounterTrigger]:
        """Evaluate all enabled triggers and return those that should fire now."""
        self.reload_if_changed()
        turn_count = self.get_turn_count(session_metadata)
        firing: list[CounterTrigger] = []

        for trigger in self._triggers:
            if not trigger.enabled:
                continue

            cond = trigger.condition

            if cond.kind == "file_line_count":
                file_path = self.workspace / cond.path
                if not file_path.exists():
                    continue

                resolved_count = cond.resolved_count()
                if resolved_count <= 0:
                    continue

                # Read cursor offset from trigger's stored cursor
                cursor_offset = trigger._cursor.get("offset", 0)
                with open(file_path, encoding="utf-8") as f:
                    total_lines = sum(1 for _ in f)
                unprocessed = total_lines - cursor_offset

                logger.info(
                    "file_line_count check: trigger_id={}, path={}, total={}, cursor={}, unprocessed={}, count={}",
                    trigger.id, file_path, total_lines, cursor_offset, unprocessed, resolved_count,
                )

                if unprocessed >= resolved_count:
                    firing.append(trigger)
                continue

            if cond.kind == "turn_count":
                last_triggered = session_metadata.get(f"{_LAST_TRIGGER_KEY_PREFIX}{trigger.id}", 0)
                count = cond.resolved_count()

                if turn_count > 0 and turn_count % count == 0 and turn_count > last_triggered:
                    firing.append(trigger)
                continue

            if cond.kind == "cron":
                # Cron triggers are checked by the cron scheduler, not here
                continue

        return firing

    def record_trigger(self, session_metadata: dict[str, Any], trigger_id: str) -> None:
        """Record that a trigger fired, updating its cursor."""
        turn_count = self.get_turn_count(session_metadata)
        session_metadata[f"{_LAST_TRIGGER_KEY_PREFIX}{trigger_id}"] = turn_count

        # Find trigger and update cursor
        for trigger in self._triggers:
            if trigger.id == trigger_id:
                self._update_trigger_cursor(trigger)

    def _update_trigger_cursor(self, trigger: CounterTrigger) -> None:
        """Update the cursor in the triggers.json file."""
        from datetime import datetime

        try:
            # Read current file
            triggers_file = trigger._triggers_file
            if not triggers_file or not triggers_file.exists():
                return

            raw = json.loads(triggers_file.read_text(encoding="utf-8"))

            # Find and update the trigger's cursor
            for t in raw.get("triggers", []):
                if t.get("id") == trigger.id:
                    # Update cursor based on condition kind
                    if trigger.condition.kind == "file_line_count":
                        file_path = self.workspace / trigger.condition.path
                        if file_path.exists():
                            with open(file_path, encoding="utf-8") as f:
                                total_lines = sum(1 for _ in f)
                            t["cursor"]["offset"] = total_lines
                            t["cursor"]["last_checked"] = datetime.utcnow().isoformat() + "Z"
                    elif trigger.condition.kind == "cron":
                        t["cursor"]["last_fired"] = datetime.utcnow().isoformat() + "Z"
                    break

            # Write back
            triggers_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug("Updated cursor for trigger {}", trigger.id)
        except Exception:
            logger.exception("Failed to update cursor for trigger {}", trigger.id)

    def load_prompt(self, trigger: CounterTrigger) -> str | None:
        """Load the system prompt file for a trigger.

        Searches in order:
        1. subagent/{category}/{name}/context/{name}_subagent.md
        2. subagent/{category}/{name}/context/{prompt_file}
        """
        if not trigger.target.prompt_file:
            # Default to standard path
            for category in ["single_session", "cross_session"]:
                for subagent_dir in (self.workspace / "subagent" / category).iterdir():
                    if not subagent_dir.is_dir():
                        continue
                    ctx_path = subagent_dir / "context" / f"{subagent_dir.name}_subagent.md"
                    if ctx_path.exists():
                        return ctx_path.read_text(encoding="utf-8")
            return None

        prompt_file = trigger.target.prompt_file
        path = self.workspace / prompt_file
        if path.exists():
            return path.read_text(encoding="utf-8")

        logger.warning(
            "Counter trigger '{}' prompt file not found: {}", trigger.id, prompt_file
        )
        return None

    def build_task(
        self,
        trigger: CounterTrigger,
        session_dir: str,
    ) -> str:
        """Format the task template with session variables."""
        template = trigger.target.task_template or ""
        return template.format(
            session_dir=session_dir,
            workspace=str(self.workspace),
        )
