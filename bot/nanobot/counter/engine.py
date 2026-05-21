"""Counter engine: evaluates count-based trigger conditions per session."""

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from nanobot.counter.types import CounterTrigger


_TURN_COUNT_KEY = "_counter_turn_count"
_LAST_TRIGGER_KEY_PREFIX = "_counter_last_trigger_"
_DEFAULT_TRIGGERS_PATH = "trigger/count/count.yaml"


class CounterEngine:
    """Loads trigger config and evaluates which triggers should fire.

    Triggers are loaded from two sources:
    1. Global triggers: global/trigger/count/count.yaml (always active)
    2. Mode-specific triggers: mode/{mode}/trigger/count/count.yaml (only when mode is active)
    """

    def __init__(self, workspace: Path, triggers_path: Path | str | None = None) -> None:
        self.workspace = Path(workspace)
        self._triggers: list[CounterTrigger] = []
        self._current_mode: str | None = None
        self._global_triggers: list[CounterTrigger] = []
        self._mode_triggers: list[CounterTrigger] = []
        self._load_global_config()
        self._load_config()

    def _load_global_config(self) -> None:
        """Load global triggers from global/trigger/count/count.yaml."""
        global_path = self.workspace / "global" / "trigger" / "count" / "count.yaml"
        if not global_path.exists():
            logger.info("Global triggers config not found at {}. No global triggers.", global_path)
            self._global_triggers = []
            return

        try:
            raw = yaml.safe_load(global_path.read_text(encoding="utf-8"))
            if not raw or not isinstance(raw, dict):
                self._global_triggers = []
                return

            triggers_raw = raw.get("triggers", [])
            self._global_triggers = [
                CounterTrigger.from_dict(t) for t in triggers_raw if isinstance(t, dict)
            ]
            enabled = [t for t in self._global_triggers if t.enabled]
            logger.info(
                "Loaded {} global trigger(s) ({} enabled) from {}",
                len(self._global_triggers),
                len(enabled),
                global_path,
            )
        except Exception:
            logger.exception("Failed to load global triggers config from {}", global_path)
            self._global_triggers = []

    def set_mode(self, mode: str | None) -> None:
        """Switch to a different mode, reloading triggers."""
        self._current_mode = mode
        self._load_config()

    def _load_config(self) -> None:
        """Load mode-specific triggers and combine with global triggers.

        Global triggers (from global/trigger/count/count.yaml) are always active.
        Mode-specific triggers (from mode/{mode}/trigger/count/count.yaml) are only active when that mode is set.
        """
        self._triggers = list(self._global_triggers)  # Start with global triggers

        if not self._current_mode:
            logger.info("No mode set, using global triggers only.")
            return

        mode_path = self.workspace / "mode" / self._current_mode / "trigger" / "count" / "count.yaml"
        if not mode_path.exists():
            logger.info("Mode triggers config not found at {}. Using global triggers only.", mode_path)
            return

        try:
            raw = yaml.safe_load(mode_path.read_text(encoding="utf-8"))
            if not raw or not isinstance(raw, dict):
                return

            triggers_raw = raw.get("triggers", [])
            mode_triggers = [
                CounterTrigger.from_dict(t) for t in triggers_raw if isinstance(t, dict)
            ]
            self._mode_triggers = mode_triggers
            self._triggers.extend(mode_triggers)  # Append mode-specific triggers

            enabled = [t for t in mode_triggers if t.enabled]
            logger.info(
                "Loaded {} mode trigger(s) ({} enabled) from {}",
                len(mode_triggers),
                len(enabled),
                mode_path,
            )
        except Exception:
            logger.exception("Failed to load mode triggers config from {}", mode_path)

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
                # Skip triggers with count <= 0 — they only fire via depends_on chain
                if resolved_count <= 0:
                    continue

                # Read unprocessed line count using cursor
                cursor_offset = self._read_cursor(trigger.id)
                with open(file_path, encoding="utf-8") as f:
                    total_lines = sum(1 for _ in f)
                unprocessed = total_lines - cursor_offset

                logger.info(
                    "file_line_count check: trigger_id={}, path={}, total={}, cursor={}, unprocessed={}, count={}",
                    trigger.id, file_path, total_lines, cursor_offset, unprocessed, resolved_count,
                )

                # Fire whenever unprocessed lines reach the threshold (repeatable)
                if unprocessed >= resolved_count:
                    firing.append(trigger)
                continue

            if cond.kind != "turn_count":
                continue

            last_triggered = session_metadata.get(f"{_LAST_TRIGGER_KEY_PREFIX}{trigger.id}", 0)
            count = cond.resolved_count()

            # Fire on first eligible turn and every N turns thereafter
            if turn_count > 0 and turn_count % count == 0 and turn_count > last_triggered:
                firing.append(trigger)

        return firing

    def _read_cursor(self, trigger_id: str) -> int:
        """Read the cursor offset for a file_line_count trigger from the cursor file."""
        import json
        # Search order: shared/, global/trigger/count/, mode-specific trigger/count/
        search_paths = [
            self.workspace / "shared",
            self.workspace / "global" / "trigger" / "count",
        ]
        if self._current_mode:
            search_paths.append(
                self.workspace / "mode" / self._current_mode / "trigger" / "count"
            )

        for cursor_base in search_paths:
            cursor_path = cursor_base / f".cursor_{trigger_id}.json"
            if cursor_path.exists():
                try:
                    data = json.loads(cursor_path.read_text(encoding="utf-8"))
                    return data.get("offset", 0)
                except (json.JSONDecodeError, IOError):
                    return 0
        return 0

    def record_trigger(self, session_metadata: dict[str, Any], trigger_id: str) -> None:
        """Record that a trigger fired at the current turn count."""
        turn_count = self.get_turn_count(session_metadata)
        session_metadata[f"{_LAST_TRIGGER_KEY_PREFIX}{trigger_id}"] = turn_count

    def load_prompt(self, trigger: CounterTrigger) -> str | None:
        """Load the system prompt file for a trigger.

        Searches in order:
        1. subagents/{prompt_file} (centralized subagent directory)
        2. mode/{mode}/subagents/{prompt_file} (mode-specific)
        3. {prompt_file} (relative to workspace)
        """
        if not trigger.target.prompt_file:
            return None

        prompt_file = trigger.target.prompt_file

        # Try subagents/ first (centralized location)
        subagents_path = self.workspace / "subagents" / prompt_file
        if subagents_path.exists():
            return subagents_path.read_text(encoding="utf-8")

        # Try mode-specific path
        if self._current_mode:
            mode_path = self.workspace / "mode" / self._current_mode / prompt_file
            if mode_path.exists():
                return mode_path.read_text(encoding="utf-8")

        # Fall back to workspace root
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
