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


def _artifact_type_matches_path(artifact_type: str, raw_path: str | None) -> bool:
    if not raw_path or artifact_type in {"", "mixed"}:
        return True
    suffix = Path(str(raw_path)).suffix.lower()
    expected = {
        "jsonl": ".jsonl",
        "json": ".json",
        "md": ".md",
        "markdown": ".md",
        "sqlite": ".sqlite",
    }.get(artifact_type)
    return expected is None or suffix == expected


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0


def _subagent_root(root: Path, name: str, scope: str | None) -> Path | None:
    if scope not in {"single_session", "cross_session"}:
        return None
    return root / "subagent" / str(scope) / name


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


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
    registered_models = capabilities.get("models") if isinstance(capabilities.get("models"), dict) else {}
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
            model = str(target.get("model") or "")
            tools = _as_list(target.get("tools"))
            output_mode = _mode_from_processor_output_path(target.get("output_path"))
            if not subagent and not processor:
                errors.append(f"{rel}:{trigger_id}: target must declare subagent or processor")
            if (subagent or processor) and not model:
                errors.append(f"{rel}:{trigger_id}: target.model is required for processor/subagent execution")
            if model and registered_models and model not in registered_models:
                errors.append(f"{rel}:{trigger_id}: model missing from config/capabilities.yaml models: {model}")
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
            if processor and processor in registered_processors and target.get("output_path"):
                processor_config = registered_processors.get(processor)
                artifact_type = (
                    str(processor_config.get("artifact_type") or "")
                    if isinstance(processor_config, dict)
                    else ""
                )
                if not _artifact_type_matches_path(artifact_type, str(target.get("output_path"))):
                    errors.append(
                        f"{rel}:{trigger_id}: output_path does not match processors.{processor}.artifact_type={artifact_type}"
                    )
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
                if subagent and subagent in registered_subagents and prompt_path and prompt_path.exists():
                    subagent_config = registered_subagents.get(subagent)
                    registered_prompt = _prompt_path(
                        root,
                        str(subagent_config.get("prompt") or "")
                        if isinstance(subagent_config, dict)
                        else "",
                    )
                    if registered_prompt and registered_prompt.exists() and prompt_path.resolve() != registered_prompt.resolve():
                        errors.append(f"{rel}:{trigger_id}: prompt_file must match registered prompt for subagent {subagent}")
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
        scope = str(item.get("scope") or "")
        expected_root = _subagent_root(root, str(name), scope)
        if prompt and prompt.exists() and expected_root and not _is_relative_to(prompt, expected_root):
            errors.append(f"config/capabilities.yaml: subagent {name} prompt must live under {expected_root.relative_to(root)}")
        writes = _as_list(item.get("writes"))
        if scope == "cross_session" and not bool(item.get("allow_session_writes", False)):
            for raw_write in writes:
                if raw_write.startswith("persona/sessions/") or "{session_uuid}" in raw_write:
                    errors.append(
                        f"config/capabilities.yaml: cross_session subagent {name} declares session-only write without allow_session_writes"
                    )
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
        artifact_type = str(item.get("artifact_type") or "")
        if artifact_type not in {"jsonl", "json", "md", "markdown", "sqlite", "mixed"}:
            errors.append(f"config/capabilities.yaml: processor {name} artifact_type is required and must be valid")
        if item.get("output") and not _artifact_type_matches_path(artifact_type, str(item.get("output"))):
            errors.append(f"config/capabilities.yaml: processor {name} output does not match artifact_type={artifact_type}")
        mode_outputs = item.get("mode_outputs") if isinstance(item.get("mode_outputs"), dict) else {}
        for mode_name, raw_output in mode_outputs.items():
            if not _artifact_type_matches_path(artifact_type, str(raw_output)):
                errors.append(
                    f"config/capabilities.yaml: processor {name} mode_outputs.{mode_name} does not match artifact_type={artifact_type}"
                )

    for name, item in registered_models.items():
        if not isinstance(item, dict):
            errors.append(f"config/capabilities.yaml: model {name} must be an object")
            continue
        for key in ("provider", "model_name", "intended_use"):
            if not str(item.get(key) or "").strip():
                errors.append(f"config/capabilities.yaml: model {name} missing required field {key}")
        for key in ("context_window", "default_max_tokens"):
            value = item.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                errors.append(f"config/capabilities.yaml: model {name} {key} must be a positive integer")
        for key in ("input_cost_per_1m", "cached_input_cost_per_1m", "output_cost_per_1m"):
            if not _positive_number(item.get(key)):
                errors.append(f"config/capabilities.yaml: model {name} {key} must be a non-negative number")

    for name, item in registered_tools.items():
        if not isinstance(item, dict):
            errors.append(f"config/capabilities.yaml: tool {name} must be an object")
            continue
        for key in ("description", "scope"):
            if not str(item.get(key) or "").strip():
                errors.append(f"config/capabilities.yaml: tool {name} missing required field {key}")
        if not isinstance(item.get("input_schema"), dict) or not item["input_schema"]:
            errors.append(f"config/capabilities.yaml: tool {name} input_schema must be a non-empty object")
        if not isinstance(item.get("output_schema"), dict) or not item["output_schema"]:
            errors.append(f"config/capabilities.yaml: tool {name} output_schema must be a non-empty object")
        permissions = item.get("permissions")
        if not isinstance(permissions, list) or not all(isinstance(p, str) and p for p in permissions):
            errors.append(f"config/capabilities.yaml: tool {name} permissions must be a non-empty string array")
        timeout_ms = item.get("timeout_ms")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or timeout_ms <= 0:
            errors.append(f"config/capabilities.yaml: tool {name} timeout_ms must be a positive integer")
        audit_fields = item.get("audit_log_fields")
        if not isinstance(audit_fields, list) or not all(isinstance(f, str) and f for f in audit_fields):
            errors.append(f"config/capabilities.yaml: tool {name} audit_log_fields must be a non-empty string array")

    budgets = capabilities.get("budgets") if isinstance(capabilities.get("budgets"), dict) else {}
    daily = budgets.get("daily") if isinstance(budgets.get("daily"), dict) else {}
    for key in ("freechat_usd", "benative_usd", "wiki_sync_usd", "background_usd"):
        if key not in daily or not _positive_number(daily.get(key)):
            errors.append(f"config/capabilities.yaml: budgets.daily.{key} must be a non-negative number")
    per_session = budgets.get("per_session") if isinstance(budgets.get("per_session"), dict) else {}
    for key in ("max_processor_runs", "max_agentic_subagent_runs"):
        value = per_session.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"config/capabilities.yaml: budgets.per_session.{key} must be a positive integer")

    return {
        "ok": not errors,
        "trigger_files": [str(p.relative_to(root)) for p in _trigger_files(root)],
        "trigger_count": trigger_count,
        "subagents": sorted(subagents),
        "registered_subagents": sorted(registered_subagents),
        "registered_models": sorted(registered_models),
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
