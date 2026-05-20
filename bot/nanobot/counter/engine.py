"""Counter engine: evaluates count-based trigger conditions per session."""

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from nanobot.counter.types import CounterTrigger


_TURN_COUNT_KEY = "_counter_turn_count"
_LAST_TRIGGER_KEY_PREFIX = "_counter_last_trigger_"
_DEFAULT_TRIGGERS_PATH = "counter/triggers.yaml"


class CounterEngine:
    """Loads trigger config and evaluates which triggers should fire."""

    def __init__(self, workspace: Path, triggers_path: Path | str | None = None) -> None:
        self.workspace = Path(workspace)
        if triggers_path is None:
            triggers_path = self.workspace / _DEFAULT_TRIGGERS_PATH
        else:
            triggers_path = Path(triggers_path)
        self.triggers_path = triggers_path
        self._triggers: list[CounterTrigger] = []
        self._load_config()

    def _load_config(self) -> None:
        """Load triggers from YAML config."""
        if not self.triggers_path.exists():
            logger.warning(
                "Counter triggers config not found at {}. No count-based subagents will run.",
                self.triggers_path,
            )
            self._triggers = []
            return

        try:
            raw = yaml.safe_load(self.triggers_path.read_text(encoding="utf-8"))
            if not raw or not isinstance(raw, dict):
                logger.warning("Counter triggers config is empty or invalid.")
                self._triggers = []
                return

            triggers_raw = raw.get("triggers", [])
            self._triggers = [
                CounterTrigger.from_dict(t) for t in triggers_raw if isinstance(t, dict)
            ]
            enabled = [t for t in self._triggers if t.enabled]
            logger.info(
                "Loaded {} counter trigger(s) ({} enabled) from {}",
                len(self._triggers),
                len(enabled),
                self.triggers_path,
            )
        except Exception:
            logger.exception("Failed to load counter triggers config from {}", self.triggers_path)
            self._triggers = []

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
        cursor_path = self.workspace / f".cursor_{trigger_id}.json"
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
        """Load the system prompt file for a trigger."""
        if not trigger.target.prompt_file:
            return None
        path = self.workspace / trigger.target.prompt_file
        if path.exists():
            return path.read_text(encoding="utf-8")
        logger.warning(
            "Counter trigger '{}' prompt file not found: {}", trigger.id, path
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
