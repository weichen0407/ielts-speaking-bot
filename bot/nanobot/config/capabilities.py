"""Project capability registry helpers.

The registry lives at ``config/capabilities.yaml`` in the project root.  This
module keeps monitor/admin/runtime code from hard-coding paths in several
places.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REGISTRY_PATH = Path("config/capabilities.yaml")


def project_root_for(path: Path | str | None = None) -> Path:
    """Return the nearest project root for a workspace-ish path."""
    start = Path(path or Path.cwd()).resolve()
    if start.is_file():
        start = start.parent

    candidates = [start, *start.parents]
    for candidate in candidates:
        if (candidate / REGISTRY_PATH).exists():
            return candidate

    if start.name == "persona":
        return start.parent
    return start


def load_capabilities(root: Path | str | None = None) -> dict[str, Any]:
    project_root = project_root_for(root)
    path = project_root / REGISTRY_PATH
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _resolve_existing(root: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    resolved = root / candidate
    return resolved if resolved.exists() else None


def trigger_files(root: Path | str | None = None) -> list[Path]:
    project_root = project_root_for(root)
    capabilities = load_capabilities(project_root)
    files: list[Path] = []
    modes = capabilities.get("modes") if isinstance(capabilities.get("modes"), dict) else {}
    for mode in modes.values():
        if not isinstance(mode, dict):
            continue
        for key in ("trigger_file", "cron_file"):
            path = _resolve_existing(project_root, mode.get(key))
            if path and path not in files:
                files.append(path)

    if files:
        return sorted(files)

    discovered: list[Path] = []
    for mode_dir in sorted((project_root / "mode").glob("*")):
        trigger_dir = mode_dir / "trigger"
        for rel in ("triggers.json", "cron/cron.yaml"):
            candidate = trigger_dir / rel
            if candidate.exists():
                discovered.append(candidate)
    return discovered


def context_prompt_files(root: Path | str | None = None) -> list[Path]:
    project_root = project_root_for(root)
    capabilities = load_capabilities(project_root)
    files: list[Path] = []

    subagents = capabilities.get("subagents") if isinstance(capabilities.get("subagents"), dict) else {}
    for subagent in subagents.values():
        if isinstance(subagent, dict):
            path = _resolve_existing(project_root, subagent.get("prompt"))
            if path and path not in files:
                files.append(path)

    modes = capabilities.get("modes") if isinstance(capabilities.get("modes"), dict) else {}
    for mode in modes.values():
        if not isinstance(mode, dict):
            continue
        context_dir = _resolve_existing(project_root, mode.get("context_dir"))
        if context_dir and context_dir.is_dir():
            for path in sorted(context_dir.glob("*.md")):
                if path not in files:
                    files.append(path)

    if files:
        return sorted(files)

    fallback = sorted(project_root.glob("subagent/*/*/context/*.md"))
    fallback.extend(sorted(project_root.glob("mode/*/context/*.md")))
    return fallback


def observability_log(
    root: Path | str | None,
    key: str,
    default_relative: str,
) -> Path:
    project_root = project_root_for(root)
    capabilities = load_capabilities(project_root)
    observability = capabilities.get("observability")
    raw = None
    if isinstance(observability, dict):
        item = observability.get(key)
        if isinstance(item, dict):
            raw = item.get("path")
    rel = str(raw or default_relative)
    path = Path(rel)
    return path if path.is_absolute() else project_root / path


def monitor_log(root: Path | str | None, key: str, default_name: str) -> tuple[Path, str]:
    path = observability_log(root, key, f"monitor/{default_name}")
    return path.parent, path.name
