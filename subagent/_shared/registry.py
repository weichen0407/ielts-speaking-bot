"""Auto-discovery mechanism for Data Processors."""

import importlib
from pathlib import Path

_INTERNAL = frozenset({"base", "registry", "manager", "utils", "__init__"})


def discover_processors() -> dict[str, type["BaseDataProcessor"]]:
    """扫描 subagent/single_session/*/processor 和 cross_session/*/processor 目录，自动发现所有 Processor 子类"""
    processors: dict[str, type["BaseDataProcessor"]] = {}

    # Scan single_session
    single_path = Path(__file__).parent.parent / "single_session"
    for subagent_dir in single_path.iterdir():
        if not subagent_dir.is_dir():
            continue
        processor_dir = subagent_dir / "processor"
        if not processor_dir.is_dir():
            continue
        name = subagent_dir.name
        try:
            cls = load_processor_class(name, "single_session")
            processors[name] = cls
        except ImportError:
            continue

    # Scan cross_session
    cross_path = Path(__file__).parent.parent / "cross_session"
    for subagent_dir in cross_path.iterdir():
        if not subagent_dir.is_dir():
            continue
        processor_dir = subagent_dir / "processor"
        if not processor_dir.is_dir():
            continue
        name = subagent_dir.name
        try:
            cls = load_processor_class(name, "cross_session")
            processors[name] = cls
        except ImportError:
            continue

    return processors


def load_processor_class(module_name: str, category: str = "single_session") -> type["BaseDataProcessor"]:
    """加载指定模块，返回 BaseDataProcessor 子类"""
    from subagent._shared.base import BaseDataProcessor as _Base

    mod = importlib.import_module(f"subagent.{category}.{module_name}.processor")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(
        f"No BaseDataProcessor subclass in subagent.{category}.{module_name}.processor"
    )
