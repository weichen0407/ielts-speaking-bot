"""Dataclasses for the count-based trigger system."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CounterCondition:
    """When should this trigger fire.

    Attributes:
        kind: "turn_count" (every N turns) or "file_line_count" (at least N unprocessed lines).
        count: Unified trigger count. For turn_count: fire every N turns.
                For file_line_count: fire when unprocessed lines >= N.
        scope: "session" (per-session counter) or "global" (shared counter).
        path: File path for file_line_count kind (relative to workspace).
        every: Deprecated alias for count (turn_count kind).
        threshold: Deprecated alias for count (file_line_count kind).
    """

    kind: Literal["turn_count", "file_line_count", "cron"] = "turn_count"
    count: int = 1
    scope: Literal["session", "global"] = "session"
    path: str = ""
    # Deprecated aliases — read only if count is not set
    every: int | None = None
    threshold: int | None = None

    def resolved_count(self) -> int:
        """Return the effective count, supporting deprecated field aliases.

        Priority: old fields (every/threshold) > new unified field (count).
        """
        if self.kind == "turn_count" and self.every is not None:
            return self.every
        if self.kind == "file_line_count" and self.threshold is not None:
            return self.threshold
        return self.count


@dataclass
class CounterTarget:
    """What to do when the trigger fires."""

    subagent: str = ""
    prompt_file: str = ""
    silent: bool = True
    task_template: str = ""
    depends_on: str | None = None  # Trigger ID that must complete before this fires
    model: str | None = None  # Override default model for this subagent (e.g. "gpt-4o-mini")


@dataclass
class CounterTrigger:
    """A single count-based trigger definition."""

    id: str
    name: str = ""
    enabled: bool = True
    condition: CounterCondition = field(default_factory=CounterCondition)
    target: CounterTarget = field(default_factory=CounterTarget)

    @classmethod
    def from_dict(cls, data: dict) -> "CounterTrigger":
        condition = CounterCondition(**data.get("condition", {}))
        target = CounterTarget(**data.get("target", {}))
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            enabled=data.get("enabled", True),
            condition=condition,
            target=target,
        )
