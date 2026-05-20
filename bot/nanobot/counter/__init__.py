"""Count-based trigger system for spawning subagents by conversation turns."""

from nanobot.counter.engine import CounterEngine
from nanobot.counter.types import CounterCondition, CounterTarget, CounterTrigger

__all__ = ["CounterEngine", "CounterCondition", "CounterTarget", "CounterTrigger"]
