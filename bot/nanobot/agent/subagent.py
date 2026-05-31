"""Subagent manager for background task execution."""

import asyncio
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.file_state import FileStates
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults, ToolsConfig
from nanobot.providers.base import LLMProvider
from nanobot.utils.prompt_templates import render_template


@dataclass(slots=True)
class SubagentStatus:
    """Real-time status of a running subagent."""

    task_id: str
    label: str
    task_description: str
    started_at: float          # time.monotonic()
    phase: str = "initializing"  # initializing | awaiting_tools | tools_completed | final_response | done | error
    iteration: int = 0
    tool_events: list = field(default_factory=list)   # [{name, status, detail}, ...]
    usage: dict = field(default_factory=dict)          # token usage
    model: str | None = None
    stop_reason: str | None = None
    error: str | None = None
    result: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    announce_result: bool = True  # whether this subagent will inject messages
    completion_event: asyncio.Event = field(default=None)

    def __post_init__(self):
        if self.completion_event is None:
            object.__setattr__(self, 'completion_event', asyncio.Event())


class _SubagentHook(AgentHook):
    """Hook for subagent execution — logs tool calls and updates status."""

    def __init__(self, task_id: str, status: SubagentStatus | None = None) -> None:
        super().__init__()
        self._task_id = task_id
        self._status = status

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tool_call in context.tool_calls:
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
            logger.debug(
                "Subagent [{}] executing: {} with arguments: {}",
                self._task_id, tool_call.name, args_str,
            )

    async def after_iteration(self, context: AgentHookContext) -> None:
        if self._status is None:
            return
        self._status.iteration = context.iteration
        self._status.tool_events = list(context.tool_events)
        self._status.usage = dict(context.usage)
        if context.error:
            self._status.error = str(context.error)


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        max_tool_result_chars: int,
        model: str | None = None,
        tools_config: ToolsConfig | None = None,
        restrict_to_workspace: bool = False,
        disabled_skills: list[str] | None = None,
        max_iterations: int | None = None,
        llm_wall_timeout_for_session: Callable[[str | None], float | None] | None = None,
        on_status_change: Callable[[str, str, str, str | None, dict[str, str]], None] | None = None,
        subagent_defaults: dict[str, str] | None = None,
    ):
        defaults = AgentDefaults()
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.tools_config = tools_config or ToolsConfig()
        self.max_tool_result_chars = max_tool_result_chars
        self.restrict_to_workspace = restrict_to_workspace
        self.disabled_skills = set(disabled_skills or [])
        self.max_iterations = (
            max_iterations
            if max_iterations is not None
            else defaults.max_tool_iterations
        )
        self.max_concurrent_subagents = defaults.max_concurrent_subagents
        self.runner = AgentRunner(provider)
        self._llm_wall_timeout_for_session = llm_wall_timeout_for_session
        self._on_status_change = on_status_change
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_statuses: dict[str, SubagentStatus] = {}
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}
        self._subagent_defaults: dict[str, str] = subagent_defaults or {}

    def _subagent_tools_config(self) -> ToolsConfig:
        """Build a ToolsConfig scoped for subagent use."""
        return ToolsConfig(
            exec=self.tools_config.exec,
            web=self.tools_config.web,
            restrict_to_workspace=self.restrict_to_workspace,
        )

    def _build_tools(
        self,
        workspace: Path | None = None,
        tools_config: ToolsConfig | None = None,
    ) -> ToolRegistry:
        """Build an isolated subagent tool registry via ToolLoader."""
        root = self.workspace if workspace is None else workspace
        registry = ToolRegistry()
        cfg = tools_config if tools_config is not None else self._subagent_tools_config()
        ctx = ToolContext(
            config=cfg,
            workspace=str(root.resolve()),
            file_state_store=FileStates(),
        )
        ToolLoader().load(ctx, registry, scope="subagent")
        return registry

    def set_provider(self, provider: LLMProvider, model: str) -> None:
        self.provider = provider
        self.model = model
        self.runner.provider = provider

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        origin_message_id: str | None = None,
        extra_system_prompt: str | None = None,
        announce_result: bool = True,
        model: str | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background. Returns task_id."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id, "session_key": session_key}

        # Resolve model: explicit param > subagent_defaults > default
        resolved_model = model
        if not resolved_model and label and label in self._subagent_defaults:
            resolved_model = self._subagent_defaults[label]
        if not resolved_model and "default" in self._subagent_defaults:
            resolved_model = self._subagent_defaults["default"]

        status = SubagentStatus(
            task_id=task_id,
            label=display_label,
            task_description=task,
            started_at=time.monotonic(),
            announce_result=announce_result,
            model=resolved_model or self.model,
        )
        self._task_statuses[task_id] = status

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, status, origin_message_id, extra_system_prompt, announce_result, resolved_model)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            self._task_statuses.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        if self._on_status_change:
            self._on_status_change(task_id, display_label, "started", None, origin)

        logger.info("Spawned subagent [{}]: {} (model={})", task_id, display_label, resolved_model or self.model)
        return task_id

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        status: SubagentStatus,
        origin_message_id: str | None = None,
        extra_system_prompt: str | None = None,
        announce_result: bool = True,
        model: str | None = None,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)
        output_paths = self._extract_output_paths(task)
        before_artifacts = self._read_artifact_snapshots(output_paths)

        async def _on_checkpoint(payload: dict) -> None:
            status.phase = payload.get("phase", status.phase)
            status.iteration = payload.get("iteration", status.iteration)

        try:
            tools = self._build_tools()
            system_prompt = self._build_subagent_prompt(extra_system_prompt=extra_system_prompt)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            sess_key = origin.get("session_key")
            llm_timeout = (
                self._llm_wall_timeout_for_session(sess_key)
                if self._llm_wall_timeout_for_session
                else None
            )
            result = await self.runner.run(AgentRunSpec(
                initial_messages=messages,
                tools=tools,
                model=model if model else self.model,
                max_iterations=self.max_iterations,
                max_tool_result_chars=self.max_tool_result_chars,
                hook=_SubagentHook(task_id, status),
                max_iterations_message="Task completed but no final response was generated.",
                error_message=None,
                fail_on_tool_error=True,
                checkpoint_callback=_on_checkpoint,
                session_key=sess_key,
                llm_timeout_s=llm_timeout,
            ))
            status.phase = "done"
            status.stop_reason = result.stop_reason

            if result.stop_reason == "tool_error":
                status.tool_events = list(result.tool_events)
                status.result = self._format_partial_progress(result)
                if announce_result:
                    await self._announce_result(
                        task_id, label, task,
                        status.result,
                        origin, "error", origin_message_id,
                    )
            elif result.stop_reason == "error":
                status.result = result.error or "Error: subagent execution failed."
                if announce_result:
                    await self._announce_result(
                        task_id, label, task,
                        status.result,
                        origin, "error", origin_message_id,
                    )
            else:
                final_result = result.final_content or "Task completed but no final response was generated."
                status.result = final_result
                logger.info("Subagent [{}] completed successfully", task_id)
                if announce_result:
                    await self._announce_result(task_id, label, task, final_result, origin, "ok", origin_message_id)

        except Exception as e:
            status.phase = "error"
            status.error = str(e)
            status.result = f"Error: {e}"
            logger.exception("Subagent [{}] failed", task_id)
            if announce_result:
                await self._announce_result(task_id, label, task, status.result, origin, "error", origin_message_id)
        finally:
            status.artifacts = self._build_artifact_changes(output_paths, before_artifacts)
            self._append_monitor_run(task_id, label, task, origin, status)
            if self._on_status_change:
                self._on_status_change(task_id, label, status.phase, status.error, origin)
            status.completion_event.set()

    def _append_monitor_run(
        self,
        task_id: str,
        label: str,
        task: str,
        origin: dict[str, str],
        status: SubagentStatus,
    ) -> None:
        """Persist a compact subagent run record for the WebUI monitor."""
        from nanobot.config.capabilities import monitor_log, project_root_for
        from nanobot.utils.monitor_rotator import append_monitor_record

        try:
            root = project_root_for(self.workspace)
            monitor_dir, log_name = monitor_log(root, "subagent_runs", "subagent_runs.jsonl")
            record = {
                "timestamp": datetime.now().isoformat(),
                "task_id": task_id,
                "label": label,
                "phase": status.phase,
                "model": status.model,
                "stop_reason": status.stop_reason,
                "error": status.error,
                "origin": origin,
                "task": task,
                "result": status.result,
                "usage": status.usage,
                "tool_events": status.tool_events,
                "artifacts": status.artifacts,
                "announce_result": status.announce_result,
            }
            append_monitor_record(monitor_dir, log_name, record)
        except Exception as e:
            logger.debug("Failed to append subagent monitor run: {}", e)

    def _extract_output_paths(self, task: str) -> list[Path]:
        """Best-effort extraction of files a subagent is expected to write."""
        paths: list[Path] = []
        for line in task.splitlines():
            if "Write to:" not in line and "Output:" not in line:
                continue
            _, raw = line.split(":", 1)
            raw = raw.strip().strip("`")
            match = re.search(r"(/[^`\s]+)", raw)
            if not match:
                continue
            path = Path(match.group(1)).expanduser()
            if path not in paths:
                paths.append(path)
        return paths[:8]

    def _read_artifact_snapshots(self, paths: list[Path]) -> dict[str, str | None]:
        snapshots: dict[str, str | None] = {}
        for path in paths:
            try:
                snapshots[str(path)] = path.read_text(encoding="utf-8") if path.exists() else None
            except OSError:
                snapshots[str(path)] = None
        return snapshots

    def _build_artifact_changes(
        self,
        paths: list[Path],
        before: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        for path in paths:
            key = str(path)
            previous = before.get(key)
            try:
                current = path.read_text(encoding="utf-8") if path.exists() else None
            except OSError as exc:
                artifacts.append({"path": key, "status": "error", "error": str(exc)})
                continue
            if current is None:
                artifacts.append({"path": key, "status": "missing", "content": ""})
                continue
            if previous == current:
                status = "unchanged"
                delta = ""
            elif previous is None:
                status = "created"
                delta = current
            elif current.startswith(previous):
                status = "appended"
                delta = current[len(previous):]
            else:
                status = "changed"
                delta = current
            artifacts.append({
                "path": key,
                "status": status,
                "content": current[-20000:],
                "delta": delta[-12000:],
                "truncated": len(current) > 20000 or len(delta) > 12000,
            })
        return artifacts

    async def wait_for_subagent(self, task_id: str) -> SubagentStatus:
        """Wait for a subagent to complete and return its final status.

        Used by counter trigger chaining to await one subagent before spawning the next.
        """
        status = self._task_statuses.get(task_id)
        if not status:
            raise ValueError(f"Unknown subagent task_id: {task_id}")
        await status.completion_event.wait()
        return status

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
        origin_message_id: str | None = None,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = render_template(
            "agent/subagent_announce.md",
            label=label,
            status_text=status_text,
            task=task,
            result=result,
        )

        # Inject as system message to trigger main agent.
        # Use session_key_override to align with the main agent's effective
        # session key (which accounts for unified sessions) so the result is
        # routed to the correct pending queue (mid-turn injection) instead of
        # being dispatched as a competing independent task.
        override = origin.get("session_key") or f"{origin['channel']}:{origin['chat_id']}"
        metadata: dict[str, Any] = {
            "injected_event": "subagent_result",
            "subagent_task_id": task_id,
        }
        if origin_message_id:
            metadata["origin_message_id"] = origin_message_id
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
            session_key_override=override,
            metadata=metadata,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    @staticmethod
    def _format_partial_progress(result) -> str:
        completed = [e for e in result.tool_events if e["status"] == "ok"]
        failure = next((e for e in reversed(result.tool_events) if e["status"] == "error"), None)
        lines: list[str] = []
        if completed:
            lines.append("Completed steps:")
            for event in completed[-3:]:
                lines.append(f"- {event['name']}: {event['detail']}")
        if failure:
            if lines:
                lines.append("")
            lines.append("Failure:")
            lines.append(f"- {failure['name']}: {failure['detail']}")
        if result.error and not failure:
            if lines:
                lines.append("")
            lines.append("Failure:")
            lines.append(f"- {result.error}")
        return "\n".join(lines) or (result.error or "Error: subagent execution failed.")

    def _build_subagent_prompt(self, extra_system_prompt: str | None = None) -> str:
        """Build a focused system prompt for the subagent."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        skills_summary = SkillsLoader(
            self.workspace,
            disabled_skills=self.disabled_skills,
        ).build_skills_summary()
        base = render_template(
            "agent/subagent_system.md",
            time_ctx=time_ctx,
            workspace=str(self.workspace),
            skills_summary=skills_summary or "",
        )
        if extra_system_prompt:
            base += "\n\n" + extra_system_prompt
        return base

    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])
                 if tid in self._running_tasks and not self._running_tasks[tid].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)

    def get_running_count_by_session(self, session_key: str) -> int:
        """Return the number of currently running subagents for a session."""
        tids = self._session_tasks.get(session_key, set())
        return sum(
            1 for tid in tids
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        )

    def get_announcing_count_by_session(self, session_key: str) -> int:
        """Return the number of running subagents that will announce results."""
        tids = self._session_tasks.get(session_key, set())
        return sum(
            1 for tid in tids
            if tid in self._running_tasks
            and not self._running_tasks[tid].done()
            and self._task_statuses.get(tid, {}).announce_result
        )
