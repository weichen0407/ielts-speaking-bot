"""通用工具函数 for Data Processors."""

import re
from pathlib import Path


def parse_kv_pairs(line: str) -> dict:
    """解析无冒号键值对 (key=value format)"""
    result = {}
    parts = line.strip().split()
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def ensure_output_dir(path: Path) -> None:
    """确保输出目录存在"""
    path.parent.mkdir(parents=True, exist_ok=True)
