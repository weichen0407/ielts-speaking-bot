"""Project capability registry helpers.

The registry lives at ``config/capabilities.yaml`` in the project root.  This
module keeps monitor/admin/runtime code from hard-coding paths in several
places.
"""

from __future__ import annotations

import os
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


def wiki_sync_allowed_modes(root: Path | str | None = None) -> set[str]:
    """Return modes allowed to feed LLM Wiki memory.

    ``NANOBOT_WIKI_SYNC_MODES`` is an operational override. The project default
    lives in ``config/capabilities.yaml`` under
    ``processors.wiki.sync.allowed_modes``. An empty set means all modes.
    """
    env_value = os.environ.get("NANOBOT_WIKI_SYNC_MODES")
    if env_value is not None:
        return _parse_mode_set(env_value, default={"freechat"})

    capabilities = load_capabilities(root)
    processors = capabilities.get("processors") if isinstance(capabilities.get("processors"), dict) else {}
    wiki = processors.get("wiki") if isinstance(processors.get("wiki"), dict) else {}
    sync = wiki.get("sync") if isinstance(wiki.get("sync"), dict) else {}
    raw = sync.get("allowed_modes")
    return _parse_mode_set(raw, default={"freechat"})


def wiki_mode_allowed(mode: str | None, root: Path | str | None = None) -> bool:
    allowed = wiki_sync_allowed_modes(root)
    if not allowed:
        return True
    return (mode or "freechat").lower() in allowed


def _parse_mode_set(raw: Any, *, default: set[str]) -> set[str]:
    if isinstance(raw, str):
        items = [item.strip().lower() for item in raw.split(",") if item.strip()]
    elif isinstance(raw, list):
        items = [str(item).strip().lower() for item in raw if str(item).strip()]
    else:
        items = []
    if not items:
        return set(default)
    if "all" in items or "*" in items:
        return set()
    return set(items)


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


def mode_trigger_file(root: Path | str | None, mode: str) -> Path | None:
    project_root = project_root_for(root)
    capabilities = load_capabilities(project_root)
    modes = capabilities.get("modes") if isinstance(capabilities.get("modes"), dict) else {}
    item = modes.get(mode)
    if isinstance(item, dict):
        path = _resolve_existing(project_root, item.get("trigger_file"))
        if path:
            return path

    fallback = project_root / "mode" / mode / "trigger" / "triggers.json"
    return fallback if fallback.exists() else None


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
