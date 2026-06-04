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
    processor: str = ""  # Processor name (e.g., "vocab", "polisher")
    execution_mode: Literal["api", "agentic"] = "api"
    agentic: bool = False
    tools: list[str] = field(default_factory=list)
    prompt_file: str = ""
    silent: bool = True
    task_template: str = ""
    depends_on: str | None = None  # Trigger ID that must complete before this fires
    model: str | None = None  # Override default model for this subagent (e.g. "deepseek-v4-flash")
    # Processor-specific fields
    input_path: str = ""  # Single input file for processor
    input_paths: list[str] = field(default_factory=list)  # Multiple input files for processor
    output_path: str = ""  # Output file for processor
    batch_size: int = 50  # Batch size for processor


@dataclass
class CounterTrigger:
    """A single count-based trigger definition."""

    id: str
    name: str = ""
    enabled: bool = True
    condition: CounterCondition = field(default_factory=CounterCondition)
    target: CounterTarget = field(default_factory=CounterTarget)
    # Internal fields (not from JSON)
    _cursor: dict = field(default_factory=dict)  # cursor state from triggers.json
    _triggers_file: "Path | None" = field(default=None)  # path to triggers.json

    @classmethod
    def from_dict(cls, data: dict) -> "CounterTrigger":
        condition = CounterCondition(**data.get("condition", {}))
        target = CounterTarget(**data.get("target", {}))
        cursor = data.get("cursor", {})
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            enabled=data.get("enabled", True),
            condition=condition,
            target=target,
            _cursor=cursor,
        )
