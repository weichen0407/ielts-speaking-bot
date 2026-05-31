"""Validate trigger-to-subagent wiring without calling an LLM API."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot"))

from nanobot.config.capabilities import load_capabilities, trigger_files  # noqa: E402


def _load_config(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def _trigger_files() -> list[Path]:
    return trigger_files(ROOT)


def _prompt_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    candidate = ROOT / raw
    if candidate.exists():
        return candidate
    matches = sorted(ROOT.glob(f"subagent/**/context/{Path(raw).name}"))
    return matches[0] if matches else candidate


def main() -> None:
    errors: list[str] = []
    trigger_count = 0
    subagents: set[str] = set()
    trigger_ids: set[str] = set()
    capabilities = load_capabilities(ROOT)
    registered_subagents = capabilities.get("subagents") if isinstance(capabilities.get("subagents"), dict) else {}
    registered_processors = capabilities.get("processors") if isinstance(capabilities.get("processors"), dict) else {}

    for file_path in _trigger_files():
        rel = file_path.relative_to(ROOT)
        try:
            config = _load_config(file_path)
        except Exception as exc:
            errors.append(f"{rel}: cannot parse config: {exc}")
            continue

        items = config.get("triggers") or config.get("cron_jobs") or []
        if not isinstance(items, list):
            errors.append(f"{rel}: trigger list is not an array")
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            trigger_count += 1
            trigger_id = item.get("id") or "<missing-id>"
            trigger_ids.add(str(trigger_id))
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            subagent = str(target.get("subagent") or "")
            if subagent:
                subagents.add(subagent)
                if subagent not in registered_subagents:
                    errors.append(f"{rel}:{trigger_id}: subagent missing from config/capabilities.yaml: {subagent}")
            prompt_file = target.get("prompt_file")
            if prompt_file:
                prompt_path = _prompt_path(str(prompt_file))
                if prompt_path is None or not prompt_path.exists():
                    errors.append(f"{rel}:{trigger_id}: prompt not found: {prompt_file}")
            condition = item.get("condition") if isinstance(item.get("condition"), dict) else {}
            if condition.get("kind") in {"turn_count", "file_line_count"}:
                try:
                    count = int(condition.get("count", 0))
                except (TypeError, ValueError):
                    count = 0
                if count < 1:
                    errors.append(f"{rel}:{trigger_id}: count must be >= 1")

    processor_files = sorted(ROOT.glob("subagent/**/processor/processor.py"))
    context_files = sorted(ROOT.glob("subagent/**/*_subagent.md"))

    for name, item in registered_subagents.items():
        if not isinstance(item, dict):
            errors.append(f"config/capabilities.yaml: subagent {name} must be an object")
            continue
        prompt = _prompt_path(str(item.get("prompt") or ""))
        if prompt is None or not prompt.exists():
            errors.append(f"config/capabilities.yaml: subagent {name} prompt not found: {item.get('prompt')}")
        for trigger_id in item.get("trigger_ids") or []:
            if str(trigger_id) not in trigger_ids:
                errors.append(f"config/capabilities.yaml: subagent {name} references unknown trigger id: {trigger_id}")

    for name, item in registered_processors.items():
        if not isinstance(item, dict):
            errors.append(f"config/capabilities.yaml: processor {name} must be an object")
            continue
        raw_path = item.get("path")
        if raw_path and not (ROOT / str(raw_path)).exists():
            errors.append(f"config/capabilities.yaml: processor {name} path not found: {raw_path}")

    print(json.dumps(
        {
            "ok": not errors,
            "trigger_files": [str(p.relative_to(ROOT)) for p in _trigger_files()],
            "trigger_count": trigger_count,
            "subagents": sorted(subagents),
            "registered_subagents": sorted(registered_subagents),
            "context_prompt_count": len(context_files),
            "processor_count": len(processor_files),
            "errors": errors,
        },
        ensure_ascii=False,
        indent=2,
    ))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
