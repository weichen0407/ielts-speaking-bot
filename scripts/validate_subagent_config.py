"""Validate trigger-to-subagent wiring without calling an LLM API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent


def _load_config(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix in {".yaml", ".yml"}:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {}


def _trigger_files() -> list[Path]:
    files: list[Path] = []
    for mode_dir in sorted((ROOT / "mode").glob("*")):
        trigger_dir = mode_dir / "trigger"
        for rel in ("triggers.json", "cron/cron.yaml"):
            candidate = trigger_dir / rel
            if candidate.exists():
                files.append(candidate)
    return files


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
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            subagent = str(target.get("subagent") or "")
            if subagent:
                subagents.add(subagent)
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

    print(json.dumps(
        {
            "ok": not errors,
            "trigger_files": [str(p.relative_to(ROOT)) for p in _trigger_files()],
            "trigger_count": trigger_count,
            "subagents": sorted(subagents),
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
