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


def _trigger_files(root: Path = ROOT) -> list[Path]:
    return trigger_files(root)


def _prompt_path(root: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    candidate = root / raw
    if candidate.exists():
        return candidate
    matches = sorted(root.glob(f"subagent/**/context/{Path(raw).name}"))
    return matches[0] if matches else candidate


def _mode_for_trigger_file(root: Path, capabilities: dict[str, Any]) -> dict[Path, str]:
    modes = capabilities.get("modes") if isinstance(capabilities.get("modes"), dict) else {}
    result: dict[Path, str] = {}
    for mode_name, mode_config in modes.items():
        if not isinstance(mode_config, dict):
            continue
        for key in ("trigger_file", "cron_file"):
            raw = mode_config.get(key)
            if not raw:
                continue
            path = root / str(raw)
            result[path.resolve()] = str(mode_name)
    return result


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _mode_from_processor_output_path(raw: str | None) -> str | None:
    if not raw:
        return None
    parts = Path(str(raw)).as_posix().split("/")
    if len(parts) >= 4 and parts[0] == "persona" and parts[1] == "processor":
        return parts[2]
    return None


def validate_config(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    trigger_count = 0
    subagents: set[str] = set()
    trigger_ids: set[str] = set()
    capabilities = load_capabilities(root)
    modes = capabilities.get("modes") if isinstance(capabilities.get("modes"), dict) else {}
    registered_subagents = capabilities.get("subagents") if isinstance(capabilities.get("subagents"), dict) else {}
    registered_processors = capabilities.get("processors") if isinstance(capabilities.get("processors"), dict) else {}
    registered_tools = capabilities.get("tools") if isinstance(capabilities.get("tools"), dict) else {}
    deprecated = capabilities.get("deprecated") if isinstance(capabilities.get("deprecated"), dict) else {}
    deprecated_subagents = set(
        (deprecated.get("subagents") if isinstance(deprecated.get("subagents"), dict) else {}).keys()
    )
    file_to_mode = _mode_for_trigger_file(root, capabilities)

    for file_path in _trigger_files(root):
        rel = file_path.relative_to(root)
        mode_name = file_to_mode.get(file_path.resolve())
        mode_config = modes.get(mode_name) if mode_name and isinstance(modes.get(mode_name), dict) else {}
        mode_subagents = set(_as_list(mode_config.get("subagents") if isinstance(mode_config, dict) else []))
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
            enabled = bool(item.get("enabled", True))
            target = item.get("target") if isinstance(item.get("target"), dict) else {}
            subagent = str(target.get("subagent") or "")
            processor = str(target.get("processor") or "")
            execution_mode = str(target.get("execution_mode") or "api")
            tools = _as_list(target.get("tools"))
            output_mode = _mode_from_processor_output_path(target.get("output_path"))
            if not subagent and not processor:
                errors.append(f"{rel}:{trigger_id}: target must declare subagent or processor")
            if subagent:
                subagents.add(subagent)
                if subagent in deprecated_subagents:
                    errors.append(f"{rel}:{trigger_id}: subagent {subagent} is deprecated and must not be referenced by triggers")
                if subagent not in registered_subagents:
                    errors.append(f"{rel}:{trigger_id}: subagent missing from config/capabilities.yaml: {subagent}")
                elif enabled and mode_subagents and subagent not in mode_subagents:
                    errors.append(f"{rel}:{trigger_id}: enabled subagent {subagent} is not registered under modes.{mode_name}.subagents")
                subagent_config = registered_subagents.get(subagent) if isinstance(registered_subagents.get(subagent), dict) else {}
                execution_modes = _as_list(subagent_config.get("execution_modes")) or ["api"]
                if execution_mode not in execution_modes:
                    errors.append(f"{rel}:{trigger_id}: execution_mode {execution_mode} not allowed for subagent {subagent}; allowed={execution_modes}")
                tool_config = subagent_config.get("tools") if isinstance(subagent_config.get("tools"), dict) else {}
                allowed_tools = set(_as_list(tool_config.get(execution_mode)))
                for tool in tools:
                    if tool not in registered_tools:
                        errors.append(f"{rel}:{trigger_id}: tool missing from config/capabilities.yaml tools: {tool}")
                    if tool not in allowed_tools:
                        errors.append(f"{rel}:{trigger_id}: tool {tool} is not allowlisted for subagent {subagent} execution_mode={execution_mode}")
            if processor and processor not in registered_processors:
                errors.append(f"{rel}:{trigger_id}: processor missing from config/capabilities.yaml: {processor}")
            if output_mode and mode_name and output_mode != mode_name:
                errors.append(f"{rel}:{trigger_id}: output_path mode {output_mode} does not match trigger mode {mode_name}")
            if processor and processor in registered_processors and output_mode and mode_name:
                processor_config = registered_processors.get(processor)
                mode_outputs = (
                    processor_config.get("mode_outputs")
                    if isinstance(processor_config, dict) and isinstance(processor_config.get("mode_outputs"), dict)
                    else {}
                )
                expected_output = mode_outputs.get(mode_name)
                if expected_output and str(expected_output) != str(target.get("output_path")):
                    errors.append(
                        f"{rel}:{trigger_id}: output_path does not match processors.{processor}.mode_outputs.{mode_name}"
                    )
            depends_on = target.get("depends_on")
            if depends_on and str(depends_on) not in trigger_ids:
                errors.append(f"{rel}:{trigger_id}: depends_on references unknown earlier trigger id: {depends_on}")
            prompt_file = target.get("prompt_file")
            if prompt_file:
                prompt_path = _prompt_path(root, str(prompt_file))
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

    processor_files = sorted(root.glob("subagent/**/processor/processor.py"))
    context_files = sorted(root.glob("subagent/**/*_subagent.md"))

    for name, item in registered_subagents.items():
        if not isinstance(item, dict):
            errors.append(f"config/capabilities.yaml: subagent {name} must be an object")
            continue
        prompt = _prompt_path(root, str(item.get("prompt") or ""))
        if prompt is None or not prompt.exists():
            errors.append(f"config/capabilities.yaml: subagent {name} prompt not found: {item.get('prompt')}")
        execution_modes = _as_list(item.get("execution_modes"))
        default_execution_mode = item.get("default_execution_mode")
        if execution_modes and default_execution_mode and str(default_execution_mode) not in execution_modes:
            errors.append(f"config/capabilities.yaml: subagent {name} default_execution_mode not in execution_modes")
        tool_config = item.get("tools") if isinstance(item.get("tools"), dict) else {}
        for mode_name, mode_tools in tool_config.items():
            for tool in _as_list(mode_tools):
                if tool not in registered_tools:
                    errors.append(f"config/capabilities.yaml: subagent {name} tools.{mode_name} references unknown tool: {tool}")
        for trigger_id in item.get("trigger_ids") or []:
            if str(trigger_id) not in trigger_ids:
                errors.append(f"config/capabilities.yaml: subagent {name} references unknown trigger id: {trigger_id}")

    for name, item in registered_processors.items():
        if not isinstance(item, dict):
            errors.append(f"config/capabilities.yaml: processor {name} must be an object")
            continue
        raw_path = item.get("path")
        if raw_path and not (root / str(raw_path)).exists():
            errors.append(f"config/capabilities.yaml: processor {name} path not found: {raw_path}")

    return {
        "ok": not errors,
        "trigger_files": [str(p.relative_to(root)) for p in _trigger_files(root)],
        "trigger_count": trigger_count,
        "subagents": sorted(subagents),
        "registered_subagents": sorted(registered_subagents),
        "registered_tools": sorted(registered_tools),
        "context_prompt_count": len(context_files),
        "processor_count": len(processor_files),
        "errors": errors,
    }


def main() -> None:
    result = validate_config(ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    errors = result["errors"]
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
