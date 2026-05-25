"""Processor Manager - manages all registered Data Processors."""

from .registry import discover_processors
from .base import BaseDataProcessor


class ProcessorManager:
    """管理所有注册的 Processor"""

    def __init__(self):
        self.processors: dict[str, BaseDataProcessor] = {}
        self._discover()

    def _discover(self):
        """启动时自动发现所有 Processor"""
        for name, cls in discover_processors().items():
            self.processors[name] = cls()

    def get(self, name: str) -> BaseDataProcessor | None:
        """根据 name 获取 Processor"""
        return self.processors.get(name)

    def list_processors(self) -> list[str]:
        """列出所有已注册的 Processor"""
        return list(self.processors.keys())
