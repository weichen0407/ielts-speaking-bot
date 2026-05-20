"""Dataclasses for the count-based trigger system."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class CounterCondition:
    """When should this trigger fire."""

    kind: Literal["turn_count"] = "turn_count"
    # Fire every N turns
    every: int = 1
    # "session" = count per session independently
    scope: Literal["session"] = "session"


@dataclass
class CounterTarget:
    """What to do when the trigger fires."""

    # Subagent identifier (used for logging / task label)
    subagent: str = ""
    # Path to the system prompt file, relative to workspace
    prompt_file: str = ""
    # If True, do not announce result to the chat
    silent: bool = True
    # Task description template. Supports {session_dir} and {workspace} placeholders.
    task_template: str = ""


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
