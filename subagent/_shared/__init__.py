"""Data Processor Framework - Auto-discovery and management of data processors."""

from .registry import discover_processors, load_processor_class
from .manager import ProcessorManager

__all__ = ["discover_processors", "load_processor_class", "ProcessorManager"]
