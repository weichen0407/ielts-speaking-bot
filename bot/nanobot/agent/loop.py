"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import os
import time
import uuid
from contextlib import AsyncExitStack, nullcontext, suppress
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent import model_presets as preset_helpers
from nanobot.agent.autocompact import AutoCompact
from nanobot.agent.context import ContextBuilder
from nanobot.agent.hook import AgentHook, CompositeHook
from nanobot.agent.memory import Consolidator, Dream
from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.agent.runner import _MAX_INJECTIONS_PER_TURN, AgentRunner, AgentRunSpec
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.file_state import FileStateStore, bind_file_states, reset_file_states
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.self import MyTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command import CommandContext, CommandRouter, register_builtin_commands
from nanobot.config.capabilities import wiki_mode_allowed, wiki_sync_interval
from nanobot.config.schema import AgentDefaults, ModelPresetConfig
from nanobot.counter.engine import CounterEngine
from nanobot.counter.types import CounterTrigger
from nanobot.providers.base import LLMProvider
from nanobot.providers.factory import ProviderSnapshot
from nanobot.session.goal_state import (
    runner_wall_llm_timeout_s,
)
from nanobot.session.manager import Session, SessionManager
from nanobot.utils.artifacts import generated_image_paths_from_messages
from nanobot.utils.document import extract_documents
from nanobot.utils.helpers import image_placeholder_text
from nanobot.utils.helpers import truncate_text as truncate_text_fn
from nanobot.utils.image_generation_intent import image_generation_prompt
from nanobot.utils.llm_runtime import LLMRuntime
from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE
from nanobot.utils.session_attachments import merge_turn_media_into_last_assistant
from nanobot.utils.trigger_monitor import append_trigger_decision
from nanobot.utils.webui_turn_helpers import (
    WEBUI_TITLE_AUTO_GENERATED_METADATA_KEY,
    WebuiTurnCoordinator,
    build_bus_progress_callback,
    mark_webui_session,
)

if TYPE_CHECKING:
    from nanobot.config.schema import (
        ChannelsConfig,
        ProviderConfig,
        ToolsConfig,
    )
    from nanobot.cron.service import CronService


UNIFIED_SESSION_KEY = "unified:default"


class TurnState(Enum):
    RESTORE = auto()
    COMPACT = auto()
    COMMAND = auto()
    BUILD = auto()
    RUN = auto()
    SAVE = auto()
    RESPOND = auto()
    DONE = auto()


@dataclass
class StateTraceEntry:
    state: TurnState
    started_at: float
    duration_ms: float
    event: str
    error: str | None = None


@dataclass
class TurnContext:
    msg: InboundMessage
    session_key: str
    state: TurnState
    turn_id: str
    session: Session | None = None

    history: list[dict[str, Any]] = field(default_factory=list)
    initial_messages: list[dict[str, Any]] = field(default_factory=list)

    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    all_messages: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""
    had_injections: bool = False

    user_persisted_early: bool = False
    save_skip: int = 0

    outbound: OutboundMessage | None = None
    generated_media: list[str] = field(default_factory=list)

    on_progress: Callable[..., Awaitable[None]] | None = None
    on_stream: Callable[[str], Awaitable[None]] | None = None
    on_stream_end: Callable[..., Awaitable[None]] | None = None
    on_retry_wait: Callable[[str], Awaitable[None]] | None = None

    pending_queue: asyncio.Queue | None = None
    pending_summary: str | None = None

    turn_wall_started_at: float = field(default_factory=time.time)
    turn_latency_ms: int | None = None

    trace: list[StateTraceEntry] = field(default_factory=list)


class AgentLoop:
    """
    The agent loop is the core processing engine.

    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """

    @property
    def current_iteration(self) -> int:
        return self._current_iteration

    @property
    def tool_names(self) -> list[str]:
        return self.tools.tool_names

    def llm_runtime(self) -> LLMRuntime:
        """Return the current provider/model pair owned by this loop."""
        self._refresh_provider_snapshot()
        return LLMRuntime(self.provider, self.model)

    TITLE_KEY = "title"

    def _load_subagent_prompt(self, filename: str) -> str | None:
        """Load a subagent prompt file from workspace."""
        path = self.workspace / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def _generate_session_title(self, session: Session) -> str:
        """Generate a short title from the first user message."""
        for msg in session.messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    # Take first 50 chars of first user message, clean it up
                    title = content.strip()[:50]
                    # Remove newlines and extra spaces
                    title = " ".join(title.split())
                    if len(content.strip()) > 50:
                        title = title.rstrip(",.!?;") + "..."
                    return title or "New Chat"
        return "New Chat"

    async def _apply_session_title(self, session: Session, _msg: InboundMessage) -> None:
        """Set session title in metadata (folder stays as UUID, topic stored in metadata["title"])."""
        # Check if title already exists
        if session.metadata.get(self.TITLE_KEY):
            return

        # Generate title from first user message and store in metadata
        title = self._generate_session_title(session)
        session.metadata[self.TITLE_KEY] = title
        # Mark as auto-generated so maybe_generate_webui_title_after_turn still runs
        # when session.metadata["webui"] is True (avoids duplicate early-return on first turn)
        if session.metadata.get("webui") is True:
            session.metadata[WEBUI_TITLE_AUTO_GENERATED_METADATA_KEY] = True
        self.sessions.save(session)
        logger.info("Applied session title: {}", title)

    async def _spawn_counter_subagent(
        self,
        session: Session,
        msg: InboundMessage,
        trigger: CounterTrigger,
        session_dir: str,
    ) -> None:
        """Spawn a counter subagent or execute a processor, then chain dependents."""
        target = trigger.target

        # Handle processor trigger
        if target.processor:
            await self._execute_processor(session, msg, trigger, session_dir)
            return

        # Handle subagent trigger (existing logic)
        prompt = self.counter_engine.load_prompt(trigger)
        if not prompt:
            self._log_counter_trigger_decision(
                session,
                trigger,
                decision="failed",
                reason="prompt_missing",
            )
            return

        task = self.counter_engine.build_task(trigger, session_dir)
        prompt = prompt.replace("{{ session_dir }}", session_dir)
        prompt = prompt.replace("{{ workspace }}", str(self.counter_engine.workspace))

        msg_id = msg.metadata.get("message_id") if msg.metadata else None

        try:
            task_id = await self.subagents.spawn(
                task=task,
                label=target.subagent,
                origin_channel=msg.channel,
                origin_chat_id=msg.chat_id,
                session_key=session.key,
                origin_message_id=msg_id,
                extra_system_prompt=prompt,
                announce_result=not target.silent,
                model=target.model,
            )
            self.counter_engine.record_trigger(session.metadata, trigger.id)
            self._log_counter_trigger_decision(
                session,
                trigger,
                decision="spawned",
                reason="subagent_spawned",
                subagent_task_id=task_id,
                cursor_after=dict(trigger._cursor),
            )
            logger.info(
                "Counter subagent [{}] spawned for session {}, chaining dependents in background",
                trigger.id,
                session.key,
            )
            self._schedule_background(
                self._chain_dependent_triggers(session, msg, trigger.id, session_dir, task_id),
            )
        except Exception as e:
            self._log_counter_trigger_decision(
                session,
                trigger,
                decision="failed",
                reason="spawn_error",
                details={"error": str(e)},
            )
            logger.warning("Failed to spawn counter subagent [{}]: {}", trigger.id, e)

    async def _execute_processor(
        self,
        session: Session,
        msg: InboundMessage,
        trigger: CounterTrigger,
        session_dir: str,
    ) -> None:
        """Execute a processor trigger."""
        from pathlib import Path

        from subagent._shared.registry import discover_processors
        from nanobot.utils.processor_monitor import (
            append_processor_run,
            append_processor_subagent_run,
            line_count,
            materialize_processor_delta,
            output_delta_records,
            update_processor_cursor,
        )

        target = trigger.target
        root = Path(self.counter_engine.workspace)
        output_path = root / target.output_path
        output_before = line_count(output_path)
        started_at = time.monotonic()
        delta_bundle = None
        model = target.model or self.model
        usage_override: dict[str, Any] | None = None
        source_paths = (
            [root / p for p in target.input_paths]
            if target.input_paths
            else [root / target.input_path]
        )
        try:
            self._publish_processor_status(
                msg,
                session,
                trigger,
                phase="started",
                model=model,
            )
            processors = discover_processors()
            processor_cls = processors.get(target.processor)
            if not processor_cls:
                logger.warning(
                    "Processor [{}] not found in registry, available: {}",
                    target.processor,
                    list(processors.keys()),
                )
                self._publish_processor_status(
                    msg,
                    session,
                    trigger,
                    phase="error",
                    error="processor_not_found",
                    model=model,
                )
                return

            processor = processor_cls()
            if hasattr(processor, "configure_llm"):
                processor.configure_llm(
                    provider=self.provider,
                    model=model,
                    retry_mode=self.provider_retry_mode,
                )
            batch_size = target.batch_size or 50

            file_line_cursor = None
            if trigger.condition.kind == "file_line_count":
                file_line_cursor = int(trigger._cursor.get("offset", 0) or 0)

            delta_bundle = materialize_processor_delta(
                root=root,
                trigger_id=trigger.id,
                source_paths=source_paths,
                file_line_cursor=file_line_cursor,
            )
            input_rows = delta_bundle.input_rows
            input_records = [item.to_record(root) for item in delta_bundle.inputs]
            input_paths_for_log = [item["path"] for item in input_records]
            cursor_before = delta_bundle.cursor_before
            cursor_after = delta_bundle.cursor_after

            if input_rows <= 0:
                append_processor_run(
                    root,
                    trigger_id=trigger.id,
                    processor=target.processor,
                    subagent=target.subagent or None,
                    execution_mode=target.execution_mode,
                    tools=list(target.tools or []),
                    mode=session.metadata.get("mode"),
                    session_key=session.key,
                    session_uuid=session.session_uuid or session.metadata.get("session_uuid"),
                    status="skipped",
                    model=model,
                    input_paths=input_paths_for_log,
                    output_path=str(output_path.relative_to(root)),
                    cursor_kind=delta_bundle.cursor_kind,
                    cursor_before=cursor_before,
                    cursor_after=cursor_after,
                    input_rows=0,
                    output_rows=0,
                    duration_ms=int((time.monotonic() - started_at) * 1000),
                )
                self._log_counter_trigger_decision(
                    session,
                    trigger,
                    decision="skipped",
                    reason="processor_no_delta",
                    cursor_after=dict(trigger._cursor),
                    details={
                        "processor": target.processor,
                        "inputs": input_records,
                    },
                )
                self._publish_processor_status(
                    msg,
                    session,
                    trigger,
                    phase="skipped",
                    input_rows=0,
                    output_rows=0,
                    model=model,
                )
                return

            if target.subagent and target.execution_mode == "api":
                usage_override = await self._run_processor_api_subagent(
                    processor=processor,
                    delta_bundle=delta_bundle,
                    output_path=output_path,
                    batch_size=batch_size,
                    model=model,
                    session=session,
                    msg=msg,
                    trigger=trigger,
                    root=root,
                    append_processor_subagent_run=append_processor_subagent_run,
                )
            elif target.subagent and target.execution_mode == "agentic":
                usage_override = await self._run_processor_agentic_subagent(
                    processor=processor,
                    delta_bundle=delta_bundle,
                    output_path=output_path,
                    model=model,
                    session=session,
                    msg=msg,
                    trigger=trigger,
                    root=root,
                    append_processor_subagent_run=append_processor_subagent_run,
                )
            # Determine input paths (single or multiple)
            elif target.input_paths:
                # Multiple input files (Level 3 processors)
                logger.info(
                    "Executing processor [{}] with inputs={}, output={}, batch_size={}",
                    target.processor,
                    delta_bundle.run_paths,
                    output_path,
                    batch_size,
                )
                # Call with input_paths for multi-input processors
                if hasattr(processor, "aprocess_all") and "input_paths" in str(inspect.signature(processor.aprocess_all)):
                    await processor.aprocess_all(
                        input_paths=delta_bundle.run_paths,
                        output_path=output_path,
                        batch_size=batch_size,
                        format="both",
                    )
                elif hasattr(processor, 'process_all') and 'input_paths' in str(inspect.signature(processor.process_all)):
                    processor.process_all(
                        input_paths=delta_bundle.run_paths,
                        output_path=output_path,
                        batch_size=batch_size,
                        format="both",
                    )
                else:
                    # Fallback for processors expecting single input_path
                    if hasattr(processor, "aprocess_all"):
                        await processor.aprocess_all(
                            input_path=delta_bundle.run_paths[0] if delta_bundle.run_paths else Path(""),
                            output_path=output_path,
                            batch_size=batch_size,
                            format="both",
                        )
                    else:
                        processor.process_all(
                            input_path=delta_bundle.run_paths[0] if delta_bundle.run_paths else Path(""),
                            output_path=output_path,
                            batch_size=batch_size,
                            format="both",
                        )
            else:
                # Single input file (Level 2 processors)
                run_input_path = delta_bundle.run_paths[0]
                logger.info(
                    "Executing processor [{}] with input={}, output={}, batch_size={}",
                    target.processor,
                    run_input_path,
                    output_path,
                    batch_size,
                )
                if hasattr(processor, "aprocess_all"):
                    await processor.aprocess_all(
                        input_path=run_input_path,
                        output_path=output_path,
                        batch_size=batch_size,
                        format="both",
                    )
                else:
                    processor.process_all(
                        input_path=run_input_path,
                        output_path=output_path,
                        batch_size=batch_size,
                        format="both",
                    )

            output_after = line_count(output_path)
            output_rows = max(output_after - output_before, 0)
            if delta_bundle.processor_cursor_after is not None:
                update_processor_cursor(
                    root,
                    trigger.id,
                    delta_bundle.processor_cursor_after,
                    inputs=delta_bundle.cursor_records_after,
                )

            self.counter_engine.record_trigger(session.metadata, trigger.id)
            usage = (
                usage_override
                if usage_override is not None
                else processor.get_usage() if hasattr(processor, "get_usage") else {}
            )
            append_processor_run(
                root,
                trigger_id=trigger.id,
                processor=target.processor,
                subagent=target.subagent or None,
                execution_mode=target.execution_mode,
                tools=list(target.tools or []),
                mode=session.metadata.get("mode"),
                session_key=session.key,
                session_uuid=session.session_uuid or session.metadata.get("session_uuid"),
                status="completed",
                model=model,
                input_paths=input_paths_for_log,
                output_path=str(output_path.relative_to(root)),
                cursor_kind=delta_bundle.cursor_kind,
                cursor_before=cursor_before,
                cursor_after=cursor_after,
                input_rows=input_rows,
                output_rows=output_rows,
                duration_ms=int((time.monotonic() - started_at) * 1000),
                usage=usage,
                output_preview=output_delta_records(output_path, start_line=output_before),
            )
            self._publish_processor_status(
                msg,
                session,
                trigger,
                phase="done",
                input_rows=input_rows,
                output_rows=output_rows,
                model=model,
            )
            self._log_counter_trigger_decision(
                session,
                trigger,
                decision="spawned",
                reason="processor_completed",
                cursor_after=dict(trigger._cursor),
                details={
                    "processor": target.processor,
                    "input_rows": input_rows,
                    "output_rows": output_rows,
                    "inputs": input_records,
                },
            )
            logger.info(
                "Processor [{}] completed, chaining dependents in background",
                target.processor,
            )
            if delta_bundle.cursor_kind == "file_line_count" or output_rows > 0:
                self._schedule_background(
                    self._chain_dependent_triggers(session, msg, trigger.id, session_dir, None),
                )
        except Exception as e:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            append_processor_run(
                root,
                trigger_id=trigger.id,
                processor=target.processor,
                subagent=target.subagent or None,
                execution_mode=target.execution_mode,
                tools=list(target.tools or []),
                mode=session.metadata.get("mode"),
                session_key=session.key,
                session_uuid=session.session_uuid or session.metadata.get("session_uuid"),
                status="error",
                model=model,
                input_paths=[str(p.relative_to(root)) if p.is_relative_to(root) else str(p) for p in source_paths],
                output_path=str(output_path.relative_to(root)) if output_path.is_relative_to(root) else str(output_path),
                cursor_kind=delta_bundle.cursor_kind if delta_bundle else None,
                cursor_before=delta_bundle.cursor_before if delta_bundle else {},
                cursor_after=delta_bundle.cursor_after if delta_bundle else {},
                input_rows=delta_bundle.input_rows if delta_bundle else 0,
                output_rows=max(line_count(output_path) - output_before, 0),
                duration_ms=duration_ms,
                error=str(e),
            )
            self._log_counter_trigger_decision(
                session,
                trigger,
                decision="failed",
                reason="processor_error",
                details={"error": str(e), "processor": target.processor},
            )
            self._publish_processor_status(
                msg,
                session,
                trigger,
                phase="error",
                error=str(e),
                input_rows=delta_bundle.input_rows if delta_bundle else 0,
                output_rows=max(line_count(output_path) - output_before, 0),
                model=model,
            )
            logger.warning("Failed to execute processor [{}]: {}", target.processor, e)
        finally:
            if delta_bundle is not None:
                delta_bundle.cleanup()

    async def _run_processor_api_subagent(
        self,
        *,
        processor: Any,
        delta_bundle: Any,
        output_path: Path,
        batch_size: int,
        model: str | None,
        session: Session,
        msg: InboundMessage,
        trigger: CounterTrigger,
        root: Path,
        append_processor_subagent_run: Callable[..., None],
    ) -> dict[str, Any]:
        """Run a processor-mediated subagent in lightweight API mode."""
        target = trigger.target
        subagent = target.subagent or target.processor
        task_id = f"api-{uuid.uuid4().hex[:8]}"
        origin = {"channel": msg.channel, "chat_id": msg.chat_id, "session_key": session.key}
        started_at = time.monotonic()
        usage_total: dict[str, int] = {}
        raw_preview = ""
        output_rows = 0
        input_rows = delta_bundle.input_rows if delta_bundle is not None else 0
        tools = list(target.tools or [])

        self._on_subagent_status_change(task_id, subagent, "started", None, origin)

        try:
            all_data: list[dict[str, Any]] = []
            for run_path in delta_bundle.run_paths:
                all_data.extend(processor.read(run_path))

            system_prompt = (
                f"You are the {subagent} subagent running in API mode.\n"
                "You do not have tool access in API mode.\n"
                "Follow the processor contract exactly and return only the required structured output.\n\n"
                f"{processor.get_system_prompt()}"
            )

            for start in range(0, len(all_data), batch_size):
                batch = all_data[start : start + batch_size]
                processed = processor.preprocess(batch)
                if not processed:
                    continue
                user_prompt = processor.prepare_subagent_input(
                    processed,
                    mode=session.metadata.get("mode"),
                    execution_mode=target.execution_mode,
                    tools=tools,
                    context={
                        "trigger_id": trigger.id,
                        "subagent": subagent,
                        "session_key": session.key,
                        "session_uuid": session.session_uuid or session.metadata.get("session_uuid"),
                    },
                )
                response = await self.provider.chat_with_retry(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    tools=None,
                    model=model,
                    max_tokens=2048,
                    temperature=0.2,
                    retry_mode=self.provider_retry_mode,
                )
                if response.finish_reason == "error":
                    raise RuntimeError(response.content or "processor-mediated subagent API call failed")
                for key, value in (response.usage or {}).items():
                    try:
                        usage_total[key] = usage_total.get(key, 0) + int(value)
                    except (TypeError, ValueError):
                        continue
                raw_output = response.content or ""
                if raw_output and not raw_preview:
                    raw_preview = raw_output[:2000]
                parsed = processor.parse_subagent_output(raw_output)
                if hasattr(processor, "attach_input_context"):
                    parsed = processor.attach_input_context(parsed, processed)
                if not parsed and hasattr(processor, "fallback_outputs"):
                    parsed = processor.fallback_outputs(processed)
                if parsed:
                    output_rows += len(parsed)
                    processor.serialize(parsed, output_path, "both")

            duration_ms = int((time.monotonic() - started_at) * 1000)
            append_processor_subagent_run(
                root,
                trigger_id=trigger.id,
                processor=target.processor,
                subagent=subagent,
                execution_mode=target.execution_mode,
                task_id=task_id,
                mode=session.metadata.get("mode"),
                session_key=session.key,
                session_uuid=session.session_uuid or session.metadata.get("session_uuid"),
                status="completed",
                model=model,
                tools=tools,
                input_rows=input_rows,
                output_rows=output_rows,
                duration_ms=duration_ms,
                usage=usage_total,
                result_preview=raw_preview,
            )
            self._on_subagent_status_change(task_id, subagent, "done", None, origin)
            return usage_total
        except Exception as exc:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            append_processor_subagent_run(
                root,
                trigger_id=trigger.id,
                processor=target.processor,
                subagent=subagent,
                execution_mode=target.execution_mode,
                task_id=task_id,
                mode=session.metadata.get("mode"),
                session_key=session.key,
                session_uuid=session.session_uuid or session.metadata.get("session_uuid"),
                status="error",
                model=model,
                tools=tools,
                input_rows=input_rows,
                output_rows=output_rows,
                duration_ms=duration_ms,
                usage=usage_total,
                result_preview=raw_preview,
                error=str(exc),
            )
            self._on_subagent_status_change(task_id, subagent, "error", str(exc), origin)
            raise

    async def _run_processor_agentic_subagent(
        self,
        *,
        processor: Any,
        delta_bundle: Any,
        output_path: Path,
        model: str | None,
        session: Session,
        msg: InboundMessage,
        trigger: CounterTrigger,
        root: Path,
        append_processor_subagent_run: Callable[..., None],
    ) -> dict[str, Any]:
        """Run a processor-mediated subagent through the tool-capable agent runtime."""
        target = trigger.target
        subagent = target.subagent or target.processor
        started_at = time.monotonic()
        input_rows = delta_bundle.input_rows if delta_bundle is not None else 0
        output_rows = 0
        tools = list(target.tools or [])
        raw_preview = ""

        try:
            all_data: list[dict[str, Any]] = []
            for run_path in delta_bundle.run_paths:
                all_data.extend(processor.read(run_path))
            processed = processor.preprocess(all_data)
            subagent_input = processor.prepare_subagent_input(
                processed,
                mode=session.metadata.get("mode"),
                execution_mode=target.execution_mode,
                tools=tools,
                context={
                    "trigger_id": trigger.id,
                    "subagent": subagent,
                    "session_key": session.key,
                    "session_uuid": session.session_uuid or session.metadata.get("session_uuid"),
                },
            )
            tool_manifest = "\n".join(f"- {name}" for name in tools) if tools else "(none)"
            extra_prompt = (
                f"# Processor-Mediated {subagent} Subagent\n\n"
                f"Execution mode: agentic\n"
                f"Allowed tool names from task config:\n{tool_manifest}\n\n"
                "Use tools only when they are useful for this task. Return only the structured output required by the processor.\n\n"
                f"Processor output contract:\n{processor.get_system_prompt()}"
            )
            task = (
                f"Analyze the compact processor input for `{subagent}`.\n"
                "Do not write files. The processor will validate and persist the final artifact.\n"
                "Return only the required structured output.\n\n"
                "## Processor Input\n"
                f"{subagent_input}"
            )
            task_id = await self.subagents.spawn(
                task=task,
                label=subagent,
                origin_channel=msg.channel,
                origin_chat_id=msg.chat_id,
                session_key=session.key,
                origin_message_id=msg.metadata.get("message_id") if msg.metadata else None,
                extra_system_prompt=extra_prompt,
                announce_result=False,
                model=model,
                allowed_tools=tools,
            )
            status = await self.subagents.wait_for_subagent(task_id)
            if status.error:
                raise RuntimeError(status.error)
            raw_output = status.result or ""
            raw_preview = raw_output[:2000]
            parsed = processor.parse_subagent_output(raw_output)
            if hasattr(processor, "attach_input_context"):
                parsed = processor.attach_input_context(parsed, processed)
            if not parsed and hasattr(processor, "fallback_outputs"):
                parsed = processor.fallback_outputs(processed)
            if parsed:
                output_rows = len(parsed)
                processor.serialize(parsed, output_path, "both")
            duration_ms = int((time.monotonic() - started_at) * 1000)
            append_processor_subagent_run(
                root,
                trigger_id=trigger.id,
                processor=target.processor,
                subagent=subagent,
                execution_mode=target.execution_mode,
                task_id=task_id,
                mode=session.metadata.get("mode"),
                session_key=session.key,
                session_uuid=session.session_uuid or session.metadata.get("session_uuid"),
                status="completed",
                model=model,
                tools=tools,
                input_rows=input_rows,
                output_rows=output_rows,
                duration_ms=duration_ms,
                usage=status.usage,
                result_preview=raw_preview,
            )
            return dict(status.usage or {})
        except Exception as exc:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            append_processor_subagent_run(
                root,
                trigger_id=trigger.id,
                processor=target.processor,
                subagent=subagent,
                execution_mode=target.execution_mode,
                task_id=f"agentic-{trigger.id}",
                mode=session.metadata.get("mode"),
                session_key=session.key,
                session_uuid=session.session_uuid or session.metadata.get("session_uuid"),
                status="error",
                model=model,
                tools=tools,
                input_rows=input_rows,
                output_rows=output_rows,
                duration_ms=duration_ms,
                result_preview=raw_preview,
                error=str(exc),
            )
            raise

    def _log_counter_trigger_decision(
        self,
        session: Session,
        trigger: CounterTrigger,
        *,
        decision: str,
        reason: str,
        subagent_task_id: str | None = None,
        cursor_after: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        source = None
        if trigger._triggers_file:
            with suppress(Exception):
                source = str(trigger._triggers_file.relative_to(self.counter_engine.workspace))
        append_trigger_decision(
            Path(self.counter_engine.workspace),
            trigger_id=trigger.id,
            name=trigger.name,
            mode=session.metadata.get("mode"),
            session_key=session.key,
            session_uuid=session.session_uuid or session.metadata.get("session_uuid"),
            kind=trigger.condition.kind,
            decision=decision,
            reason=reason,
            source=source,
            subagent=trigger.target.subagent,
            model=trigger.target.model,
            turn_count=self.counter_engine.get_turn_count(session.metadata),
            cursor_after=cursor_after,
            subagent_task_id=subagent_task_id,
            details=details,
        )

    async def _chain_dependent_triggers(
        self,
        session: Session,
        msg: InboundMessage,
        completed_trigger_id: str,
        session_dir: str,
        task_id: str | None,
    ) -> None:
        """Wait for a subagent to complete, then spawn any dependent triggers."""
        try:
            # For subagent triggers, wait for completion
            if task_id is not None:
                await self.subagents.wait_for_subagent(task_id)
                logger.info(
                    "Subagent [{}] completed, checking for dependent triggers of {}",
                    task_id,
                    completed_trigger_id,
                )
            else:
                logger.info(
                    "Processor [{}] completed (no task_id), checking for dependent triggers",
                    completed_trigger_id,
                )

            chained = [
                t for t in self.counter_engine._triggers
                if t.enabled and t.target.depends_on == completed_trigger_id
            ]
            for trigger in chained:
                await self._spawn_counter_subagent(session, msg, trigger, session_dir)
        except Exception as e:
            logger.warning(
                "Failed to chain dependent triggers after [{}]: {}",
                completed_trigger_id,
                e,
            )

    async def _on_session_inactive(self, session_key: str) -> None:
        """Called when a session becomes inactive (user switched to another session).
        Spawns memory subagent to update user profile based on conversation.
        """
        if not session_key:
            return

        # Get the session and check if it has meaningful content
        session = self.sessions.get_or_create(session_key)
        if len(session.messages) < 2:  # Need at least a user msg + assistant response
            return

        # Check if this session already had memory subagent run recently
        last_memory = session.metadata.get("_last_memory_update", 0)
        import time
        if time.time() - last_memory < 300:  # Skip if ran within last 5 minutes
            return

        session.metadata["_last_memory_update"] = time.time()

        # Spawn memory subagent for this session
        session_dir = str(self.sessions._get_session_dir(session_key))
        workspace_str = str(self.workspace)
        memory_prompt = self._load_subagent_prompt("subagents/memory_subagent.md")

        if not memory_prompt:
            return

        # Build memory update task - write to user-level memory file
        memory_task = (
            f"Update user memory profile based on this conversation session.\n\n"
            f"Session directory: {session_dir}\n"
            f"Read: {session_dir}/thread.jsonl\n"
            f"Write to: {workspace_str}/persona/memory/MEMORY.md\n\n"
            f"Also read: {workspace_str}/subagent/cross_session/memory_cron/formats/memory_format.md for output format"
        )

        # Substitute placeholders
        memory_prompt = memory_prompt.replace("{{ session_dir }}", session_dir)
        memory_prompt = memory_prompt.replace("{{ workspace }}", workspace_str)

        try:
            await self.subagents.spawn(
                task=memory_task,
                label="memory",
                origin_channel="system",
                origin_chat_id="memory",
                session_key=session_key,
                origin_message_id=None,
                extra_system_prompt=memory_prompt,
                announce_result=False,  # Silent - only write to files
            )
            logger.info("Spawned memory subagent for inactive session {}", session_key)
        except Exception as e:
            logger.warning("Failed to spawn memory subagent for session {}: {}", session_key, e)

    _RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
    _PENDING_USER_TURN_KEY = "pending_user_turn"

    # Event-driven state transition table.
    # Handlers return an event string; the driver looks up the next state here.
    _TRANSITIONS: dict[tuple[TurnState, str], TurnState] = {
        (TurnState.RESTORE, "ok"): TurnState.COMPACT,
        (TurnState.COMPACT, "ok"): TurnState.COMMAND,
        (TurnState.COMMAND, "dispatch"): TurnState.BUILD,
        (TurnState.COMMAND, "shortcut"): TurnState.DONE,
        (TurnState.BUILD, "ok"): TurnState.RUN,
        (TurnState.RUN, "ok"): TurnState.SAVE,
        (TurnState.SAVE, "ok"): TurnState.RESPOND,
        (TurnState.RESPOND, "ok"): TurnState.DONE,
    }

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int | None = None,
        context_window_tokens: int | None = None,
        context_block_limit: int | None = None,
        max_tool_result_chars: int | None = None,
        provider_retry_mode: str = "standard",
        tool_hint_max_length: int | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        timezone: str | None = None,
        session_ttl_minutes: int = 0,
        consolidation_ratio: float = 0.5,
        max_messages: int = 120,
        hooks: list[AgentHook] | None = None,
        unified_session: bool = False,
        disabled_skills: list[str] | None = None,
        tools_config: ToolsConfig | None = None,
        image_generation_provider_config: ProviderConfig | None = None,
        image_generation_provider_configs: dict[str, ProviderConfig] | None = None,
        provider_snapshot_loader: Callable[..., ProviderSnapshot] | None = None,
        provider_signature: tuple[object, ...] | None = None,
        model_presets: dict[str, ModelPresetConfig] | None = None,
        model_preset: str | None = None,
        preset_snapshot_loader: preset_helpers.PresetSnapshotLoader | None = None,
        runtime_model_publisher: Callable[[str, str | None], None] | None = None,
        subagent_defaults: dict[str, str] | None = None,
    ):
        from nanobot.config.schema import ToolsConfig

        _tc = tools_config or ToolsConfig()
        defaults = AgentDefaults()
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self._provider_snapshot_loader = provider_snapshot_loader
        self._preset_snapshot_loader = preset_snapshot_loader
        self._runtime_model_publisher = runtime_model_publisher
        self._provider_signature = provider_signature
        self._default_selection_signature = preset_helpers.default_selection_signature(provider_signature)
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = (
            max_iterations if max_iterations is not None else defaults.max_tool_iterations
        )
        self.context_window_tokens = (
            context_window_tokens
            if context_window_tokens is not None
            else defaults.context_window_tokens
        )
        self.context_block_limit = context_block_limit
        self.max_tool_result_chars = (
            max_tool_result_chars
            if max_tool_result_chars is not None
            else defaults.max_tool_result_chars
        )
        self.provider_retry_mode = provider_retry_mode
        self.tool_hint_max_length = (
            tool_hint_max_length if tool_hint_max_length is not None
            else defaults.tool_hint_max_length
        )
        self.tools_config = _tc
        self.web_config = _tc.web
        self.exec_config = _tc.exec
        self._image_generation_provider_configs = dict(image_generation_provider_configs or {})
        if (
            image_generation_provider_config is not None
            and "openrouter" not in self._image_generation_provider_configs
        ):
            self._image_generation_provider_configs["openrouter"] = image_generation_provider_config
        self.cron_service = cron_service
        self.counter_engine = CounterEngine(workspace)
        self.restrict_to_workspace = restrict_to_workspace
        self._start_time = time.time()
        self._last_usage: dict[str, int] = {}
        self._pending_turn_latency_ms: dict[str, int] = {}
        self._extra_hooks: list[AgentHook] = hooks or []

        self.context = ContextBuilder(workspace, timezone=timezone, disabled_skills=disabled_skills)
        self.sessions = session_manager or SessionManager(workspace)
        self._webui_turns = WebuiTurnCoordinator(
            bus=self.bus,
            sessions=self.sessions,
            schedule_background=lambda coro: self._schedule_background(coro),
        )
        self.tools = ToolRegistry()
        # One file-read/write tracker per logical session. The tool registry is
        # shared by this loop, so tools resolve the active state via contextvars.
        self._file_state_store = FileStateStore()
        self.runner = AgentRunner(provider)
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            tools_config=_tc,
            max_tool_result_chars=self.max_tool_result_chars,
            restrict_to_workspace=restrict_to_workspace,
            disabled_skills=disabled_skills,
            max_iterations=self.max_iterations,
            llm_wall_timeout_for_session=lambda sk: runner_wall_llm_timeout_s(self.sessions, sk),
            on_status_change=self._on_subagent_status_change,
            subagent_defaults=subagent_defaults,
        )
        self._unified_session = unified_session
        self._max_messages = max_messages if max_messages > 0 else 120
        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stacks: dict[str, AsyncExitStack] = {}
        self._mcp_connected = False
        self._mcp_connecting = False
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._background_tasks: list[asyncio.Task] = []
        self._session_locks: dict[str, asyncio.Lock] = {}
        # Per-session pending queues for mid-turn message injection.
        # When a session has an active task, new messages for that session
        # are routed here instead of creating a new task.
        self._pending_queues: dict[str, asyncio.Queue] = {}
        # Track last active session for memory update triggers
        self._last_active_session_key: str | None = None
        # NANOBOT_MAX_CONCURRENT_REQUESTS: <=0 means unlimited; default 3.
        _max = int(os.environ.get("NANOBOT_MAX_CONCURRENT_REQUESTS", "3"))
        self._concurrency_gate: asyncio.Semaphore | None = (
            asyncio.Semaphore(_max) if _max > 0 else None
        )
        self.consolidator = Consolidator(
            store=self.context.memory,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=self.context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
            max_completion_tokens=provider.generation.max_tokens,
            consolidation_ratio=consolidation_ratio,
        )
        self.auto_compact = AutoCompact(
            sessions=self.sessions,
            consolidator=self.consolidator,
            session_ttl_minutes=session_ttl_minutes,
        )
        self.dream = Dream(
            store=self.context.memory,
            provider=provider,
            model=self.model,
        )
        self.model_presets: dict[str, ModelPresetConfig] = model_presets or {}
        self._active_preset: str | None = None
        if model_preset:
            self.set_model_preset(model_preset, publish_update=False)
        self._register_default_tools()
        self._runtime_vars: dict[str, Any] = {}
        self._current_iteration: int = 0
        self.commands = CommandRouter()
        register_builtin_commands(self.commands)

    @classmethod
    def from_config(
        cls,
        config: Any,
        bus: MessageBus | None = None,
        **extra: Any,
    ) -> AgentLoop:
        """Create an AgentLoop from config with the common parameter set.

        Extra keyword arguments are forwarded to ``AgentLoop.__init__``,
        allowing callers to override or extend the standard config-derived
        parameters (e.g. ``cron_service``, ``session_manager``).
        """
        from nanobot.providers.factory import make_provider

        if bus is None:
            bus = MessageBus()
        defaults = config.agents.defaults
        provider = extra.pop("provider", None) or make_provider(config)
        resolved = config.resolve_preset()
        model = extra.pop("model", None) or resolved.model
        context_window_tokens = extra.pop("context_window_tokens", None) or resolved.context_window_tokens
        provider_snapshot_loader = extra.pop("provider_snapshot_loader", None)
        preset_snapshot_loader = extra.pop("preset_snapshot_loader", None) or preset_helpers.make_preset_snapshot_loader(
            config,
            provider_snapshot_loader,
        )
        return cls(
            bus=bus,
            provider=provider,
            workspace=config.workspace_path,
            model=model,
            max_iterations=defaults.max_tool_iterations,
            context_window_tokens=context_window_tokens,
            context_block_limit=defaults.context_block_limit,
            max_tool_result_chars=defaults.max_tool_result_chars,
            provider_retry_mode=defaults.provider_retry_mode,
            tool_hint_max_length=defaults.tool_hint_max_length,
            restrict_to_workspace=config.tools.restrict_to_workspace,
            mcp_servers=config.tools.mcp_servers,
            channels_config=config.channels,
            timezone=defaults.timezone,
            unified_session=defaults.unified_session,
            disabled_skills=defaults.disabled_skills,
            session_ttl_minutes=defaults.session_ttl_minutes,
            consolidation_ratio=defaults.consolidation_ratio,
            max_messages=defaults.max_messages,
            tools_config=config.tools,
            model_presets=preset_helpers.configured_model_presets(config),
            model_preset=defaults.model_preset,
            provider_snapshot_loader=provider_snapshot_loader,
            preset_snapshot_loader=preset_snapshot_loader,
            subagent_defaults=config.agents.subagent_defaults,
            **extra,
        )

    def _on_subagent_status_change(
        self,
        task_id: str,
        label: str,
        phase: str,
        error: str | None,
        origin: dict[str, str],
    ) -> None:
        """Called when a subagent starts or completes. Broadcasts via message bus."""
        # Fire-and-forget: we don't await the bus publish because this runs
        # from inside subagent callbacks where blocking is undesirable.
        chat_id = origin.get("chat_id", "direct")
        session_key = origin.get("session_key")
        asyncio.create_task(
            self.bus.publish_outbound(
                OutboundMessage(
                    channel=origin.get("channel", "cli"),
                    chat_id=chat_id,
                    content="",
                    metadata={
                        "_subagent_status": True,
                        "task_id": task_id,
                        "label": label,
                        "phase": phase,
                        "error": error,
                        "session_key": session_key,
                    },
                )
            )
        )

    def _publish_processor_status(
        self,
        msg: InboundMessage,
        session: Session,
        trigger: CounterTrigger,
        *,
        phase: str,
        error: str | None = None,
        input_rows: int | None = None,
        output_rows: int | None = None,
        model: str | None = None,
    ) -> None:
        """Broadcast processor lifecycle events so WebUI can show background toasts."""
        target = trigger.target
        task_id = f"processor:{trigger.id}:{session.session_uuid or session.key}"
        metadata: dict[str, Any] = {
            "_processor_status": True,
            "task_id": task_id,
            "trigger_id": trigger.id,
            "processor": target.processor,
            "subagent": target.subagent,
            "execution_mode": target.execution_mode,
            "agentic": bool(target.agentic),
            "tools": list(target.tools or []),
            "label": target.processor or trigger.id,
            "phase": phase,
            "error": error,
            "session_key": session.key,
            "session_uuid": session.session_uuid or session.metadata.get("session_uuid"),
            "mode": session.metadata.get("mode"),
            "model": model,
        }
        if input_rows is not None:
            metadata["input_rows"] = int(input_rows)
        if output_rows is not None:
            metadata["output_rows"] = int(output_rows)

        asyncio.create_task(
            self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="",
                    metadata=metadata,
                )
            )
        )

    def _sync_subagent_runtime_limits(self) -> None:
        """Keep subagent runtime limits aligned with mutable loop settings."""
        self.subagents.max_iterations = self.max_iterations

    def _apply_provider_snapshot(
        self,
        snapshot: ProviderSnapshot,
        *,
        publish_update: bool = True,
        model_preset: str | None = None,
    ) -> None:
        """Swap model/provider for future turns without disturbing an active one."""
        provider = snapshot.provider
        model = snapshot.model
        context_window_tokens = snapshot.context_window_tokens
        old_model = self.model
        self.provider = provider
        self.model = model
        self.context_window_tokens = context_window_tokens
        self.runner.provider = provider
        self.subagents.set_provider(provider, model)
        self.consolidator.set_provider(provider, model, context_window_tokens)
        self.dream.set_provider(provider, model)
        self._provider_signature = snapshot.signature
        if publish_update and self._runtime_model_publisher is not None:
            self._runtime_model_publisher(
                self.model,
                model_preset if model_preset is not None else self.model_preset,
            )
        logger.info("Runtime model switched for next turn: {} -> {}", old_model, model)

    def _refresh_provider_snapshot(self) -> None:
        if self._provider_snapshot_loader is None:
            return
        try:
            snapshot = self._provider_snapshot_loader()
        except Exception:
            logger.exception("Failed to refresh provider config")
            return
        default_selection = preset_helpers.default_selection_signature(snapshot.signature)
        if self._active_preset and self._default_selection_signature in (None, default_selection):
            self._default_selection_signature = default_selection
            try:
                snapshot = self._build_model_preset_snapshot(self._active_preset)
            except Exception:
                logger.exception("Failed to refresh active model preset")
                return
        else:
            self._active_preset = None
            self._default_selection_signature = default_selection
        if snapshot.signature == self._provider_signature:
            return
        self._default_selection_signature = preset_helpers.default_selection_signature(snapshot.signature)
        self._apply_provider_snapshot(snapshot)

    @property
    def model_preset(self) -> str | None:
        return self._active_preset

    @model_preset.setter
    def model_preset(self, name: str | None) -> None:
        self.set_model_preset(name)

    def _build_model_preset_snapshot(self, name: str) -> ProviderSnapshot:
        return preset_helpers.build_runtime_preset_snapshot(
            name=name,
            presets=self.model_presets,
            provider=self.provider,
            loader=self._preset_snapshot_loader,
        )

    def set_model_preset(self, name: str | None, *, publish_update: bool = True) -> None:
        """Resolve a preset by name and apply all runtime model dependents."""
        name = preset_helpers.normalize_preset_name(name, self.model_presets)
        snapshot = self._build_model_preset_snapshot(name)
        self._apply_provider_snapshot(snapshot, publish_update=publish_update, model_preset=name)
        self._active_preset = name

    def _register_default_tools(self) -> None:
        """Register the default set of tools via plugin loader."""
        from nanobot.agent.tools.context import ToolContext
        from nanobot.agent.tools.loader import ToolLoader

        ctx = ToolContext(
            config=self.tools_config,
            workspace=str(self.workspace),
            bus=self.bus,
            subagent_manager=self.subagents,
            cron_service=self.cron_service,
            sessions=self.sessions,
            provider_snapshot_loader=self._provider_snapshot_loader,
            image_generation_provider_configs=self._image_generation_provider_configs,
            timezone=self.context.timezone or "UTC",
        )
        loader = ToolLoader()
        registered = loader.load(ctx, self.tools)

        # MyTool needs runtime state reference — manual registration
        if self.tools_config.my.enable:
            self.tools.register(
                MyTool(runtime_state=self, modify_allowed=self.tools_config.my.allow_set)
            )
            registered.append("my")

        logger.info("Registered {} tools: {}", len(registered), registered)

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers

        try:
            self._mcp_stacks = await connect_mcp_servers(self._mcp_servers, self.tools)
            if self._mcp_stacks:
                self._mcp_connected = True
            else:
                logger.warning("No MCP servers connected successfully (will retry next message)")
        except asyncio.CancelledError:
            logger.warning("MCP connection cancelled (will retry next message)")
            self._mcp_stacks.clear()
        except BaseException as e:
            logger.warning("Failed to connect MCP servers (will retry next message): {}", e)
            self._mcp_stacks.clear()
        finally:
            self._mcp_connecting = False

    def _set_tool_context(
        self, channel: str, chat_id: str,
        message_id: str | None = None, metadata: dict | None = None,
        session_key: str | None = None,
    ) -> None:
        """Update context for all tools that need routing info."""
        from nanobot.agent.tools.context import ContextAware, RequestContext

        if session_key is not None:
            effective_key = session_key
        elif self._unified_session:
            effective_key = UNIFIED_SESSION_KEY
        else:
            effective_key = f"{channel}:{chat_id}"

        request_ctx = RequestContext(
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            session_key=effective_key,
            metadata=dict(metadata or {}),
        )

        for name in self.tools.tool_names:
            tool = self.tools.get(name)
            if tool and isinstance(tool, ContextAware):
                tool.set_context(request_ctx)

    @staticmethod
    def _runtime_chat_id(msg: InboundMessage) -> str:
        """Return the chat id shown in runtime metadata for the model."""
        return str(msg.metadata.get("context_chat_id") or msg.chat_id)

    async def _build_bus_progress_callback(
        self, msg: InboundMessage
    ) -> Callable[..., Awaitable[None]]:
        """Build a progress callback that publishes to the message bus."""
        return build_bus_progress_callback(self.bus, msg)

    async def _build_retry_wait_callback(
        self, msg: InboundMessage
    ) -> Callable[[str], Awaitable[None]]:
        """Build a retry-wait callback that publishes to the message bus."""

        async def _on_retry_wait(content: str) -> None:
            meta = dict(msg.metadata or {})
            meta["_retry_wait"] = True
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=meta,
                )
            )

        return _on_retry_wait

    def _persist_user_message_early(
        self,
        msg: InboundMessage,
        session: Session,
        **kwargs: Any,
    ) -> bool:
        """Persist the triggering user message before the turn starts.

        Returns True if the message was persisted.
        """
        media_paths = [p for p in (msg.media or []) if isinstance(p, str) and p]
        has_text = isinstance(msg.content, str) and msg.content.strip()
        if has_text or media_paths:
            extra: dict[str, Any] = {"media": list(media_paths)} if media_paths else {}
            extra.update(kwargs)
            text = msg.content if isinstance(msg.content, str) else ""
            session.add_message("user", text, **extra)
            self._mark_pending_user_turn(session)
            self.sessions.save(session)
            return True
        return False

    def _build_initial_messages(
        self,
        msg: InboundMessage,
        session: Session,
        history: list[dict[str, Any]],
        pending_summary: str | None,
    ) -> list[dict[str, Any]]:
        """Build the initial message list for the LLM turn."""
        session_notes = self.sessions.get_session_notes(session.key)
        session_dir = str(self.sessions._get_session_dir(session.key))
        mode = session.metadata.get("mode")
        return self.context.build_messages(
            history=history,
            current_message=image_generation_prompt(msg.content, msg.metadata),
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=self._runtime_chat_id(msg),
            sender_id=msg.sender_id,
            session_summary=pending_summary,
            session_notes=session_notes,
            session_dir=session_dir,
            session_metadata=session.metadata,
            mode=mode,
        )

    async def _dispatch_command_inline(
        self,
        msg: InboundMessage,
        key: str,
        raw: str,
        dispatch_fn: Callable[[CommandContext], Awaitable[OutboundMessage | None]],
    ) -> None:
        """Dispatch a command directly from the run() loop and publish the result."""
        ctx = CommandContext(msg=msg, session=None, key=key, raw=raw, loop=self)
        result = await dispatch_fn(ctx)
        if result:
            await self.bus.publish_outbound(result)
        else:
            logger.warning("Command '{}' matched but dispatch returned None", raw)

    async def _cancel_active_tasks(self, key: str) -> int:
        """Cancel and await all active tasks and subagents for *key*.

        Returns the total number of cancelled tasks + subagents.
        """
        tasks = self._active_tasks.pop(key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await t
        sub_cancelled = await self.subagents.cancel_by_session(key)
        return cancelled + sub_cancelled

    def _effective_session_key(self, msg: InboundMessage) -> str:
        """Return the session key used for task routing and mid-turn injections."""
        if self._unified_session and not msg.session_key_override:
            return UNIFIED_SESSION_KEY
        return msg.session_key

    def _replay_token_budget(self) -> int:
        """Derive a token budget for session history replay from the context window."""
        if self.context_window_tokens <= 0:
            return 0
        max_output = getattr(getattr(self.provider, "generation", None), "max_tokens", 4096)
        try:
            reserved_output = int(max_output)
        except (TypeError, ValueError):
            reserved_output = 4096
        budget = self.context_window_tokens - max(1, reserved_output) - 1024
        return budget if budget > 0 else max(128, self.context_window_tokens // 2)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        on_retry_wait: Callable[[str], Awaitable[None]] | None = None,
        *,
        session: Session | None = None,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
        pending_queue: asyncio.Queue | None = None,
    ) -> tuple[str | None, list[str], list[dict], str, bool]:
        """Run the agent iteration loop.

        *on_stream*: called with each content delta during streaming.
        *on_stream_end(resuming)*: called when a streaming session finishes.
        ``resuming=True`` means tool calls follow (spinner should restart);
        ``resuming=False`` means this is the final response.

        Returns (final_content, tools_used, messages, stop_reason, had_injections).
        """
        self._sync_subagent_runtime_limits()

        loop_hook = AgentProgressHook(
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            metadata=metadata,
            session_key=session_key,
            tool_hint_max_length=self.tool_hint_max_length,
            set_tool_context=self._set_tool_context,
            on_iteration=lambda iteration: setattr(self, "_current_iteration", iteration),
        )
        hook: AgentHook = (
            CompositeHook([loop_hook] + self._extra_hooks) if self._extra_hooks else loop_hook
        )

        async def _checkpoint(payload: dict[str, Any]) -> None:
            if session is None:
                return
            self._set_runtime_checkpoint(session, payload)

        async def _drain_pending(*, limit: int = _MAX_INJECTIONS_PER_TURN) -> list[dict[str, Any]]:
            """Drain follow-up messages from the pending queue.

            When no messages are immediately available but sub-agents
            spawned in this dispatch are still running, blocks until at
            least one result arrives (or timeout).  This keeps the runner
            loop alive so subsequent sub-agent completions are consumed
            in-order rather than dispatched separately.
            """
            if pending_queue is None:
                return []

            def _to_user_message(pending_msg: InboundMessage) -> dict[str, Any]:
                content = pending_msg.content
                media = pending_msg.media if pending_msg.media else None
                if media:
                    content, media = extract_documents(content, media)
                    media = media or None
                user_content = self.context._build_user_content(content, media)
                return {"role": "user", "content": user_content}

            items: list[dict[str, Any]] = []
            while len(items) < limit:
                try:
                    items.append(_to_user_message(pending_queue.get_nowait()))
                except asyncio.QueueEmpty:
                    break

            # Block if nothing drained but sub-agents spawned in this dispatch
            # are still running and will announce results.
            # Non-announcing subagents (announce_result=False) don't inject messages
            # so we shouldn't wait for them.
            if (not items
                    and session is not None
                    and self.subagents.get_announcing_count_by_session(session.key) > 0):
                try:
                    msg = await asyncio.wait_for(pending_queue.get(), timeout=300)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Timeout waiting for sub-agent completion in session {}",
                        session.key,
                    )
                    return items
                items.append(_to_user_message(msg))
                while len(items) < limit:
                    try:
                        items.append(_to_user_message(pending_queue.get_nowait()))
                    except asyncio.QueueEmpty:
                        break

            return items

        active_session_key = session.key if session else session_key
        file_state_token = bind_file_states(self._file_state_store.for_session(active_session_key))
        try:
            result = await self.runner.run(AgentRunSpec(
                initial_messages=initial_messages,
                tools=self.tools,
                model=self.model,
                max_iterations=self.max_iterations,
                max_tool_result_chars=self.max_tool_result_chars,
                hook=hook,
                error_message="Sorry, I encountered an error calling the AI model.",
                concurrent_tools=True,
                workspace=self.workspace,
                session_key=session.key if session else None,
                context_window_tokens=self.context_window_tokens,
                context_block_limit=self.context_block_limit,
                provider_retry_mode=self.provider_retry_mode,
                progress_callback=on_progress,
                stream_progress_deltas=on_stream is not None,
                retry_wait_callback=on_retry_wait,
                checkpoint_callback=_checkpoint,
                injection_callback=_drain_pending,
                # Sustained goals may legitimately exceed NANOBOT_LLM_TIMEOUT_S; idle stall
                # is still capped by NANOBOT_STREAM_IDLE_TIMEOUT_S in streaming providers.
                llm_timeout_s=runner_wall_llm_timeout_s(
                    self.sessions,
                    session.key if session is not None else session_key,
                    metadata=(session.metadata if session is not None else None),
                ),
            ))
        finally:
            reset_file_states(file_state_token)
        self._last_usage = result.usage
        if result.stop_reason == "max_iterations":
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            # Push final content through stream so streaming channels (e.g. Feishu)
            # update the card instead of leaving it empty.
            if on_stream and on_stream_end:
                await on_stream(result.final_content or "")
                await on_stream_end(resuming=False)
        elif result.stop_reason == "error":
            logger.error("LLM returned error: {}", (result.final_content or "")[:200])
        return result.final_content, result.tools_used, result.messages, result.stop_reason, result.had_injections

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                self.auto_compact.check_expired(
                    self._schedule_background,
                    active_session_keys=self._pending_queues.keys(),
                )
                # Check notes AI queue for pending tasks
                await self._check_notes_ai_queue()
                continue
            except asyncio.CancelledError:
                # Preserve real task cancellation so shutdown can complete cleanly.
                # Only ignore non-task CancelledError signals that may leak from integrations.
                if not self._running or asyncio.current_task().cancelling():
                    raise
                continue
            except Exception as e:
                logger.warning("Error consuming inbound message: {}, continuing...", e)
                continue

            raw = msg.content.strip()
            if self.commands.is_priority(raw):
                await self._dispatch_command_inline(
                    msg, msg.session_key, raw,
                    self.commands.dispatch_priority,
                )
                continue
            effective_key = self._effective_session_key(msg)
            # If this session already has an active pending queue (i.e. a task
            # is processing this session), route the message there for mid-turn
            # injection instead of creating a competing task.
            if effective_key in self._pending_queues:
                # Non-priority commands must not be queued for injection;
                # dispatch them directly (same pattern as priority commands).
                if self.commands.is_dispatchable_command(raw):
                    await self._dispatch_command_inline(
                        msg, effective_key, raw,
                        self.commands.dispatch,
                    )
                    continue
                pending_msg = msg
                if effective_key != msg.session_key:
                    pending_msg = dataclasses.replace(
                        msg,
                        session_key_override=effective_key,
                    )
                try:
                    self._pending_queues[effective_key].put_nowait(pending_msg)
                except asyncio.QueueFull:
                    logger.warning(
                        "Pending queue full for session {}, falling back to queued task",
                        effective_key,
                    )
                else:
                    logger.info(
                        "Routed follow-up message to pending queue for session {}",
                        effective_key,
                    )
                    continue
            # Detect session switch: if last active session is different from current
            if (self._last_active_session_key
                    and self._last_active_session_key != effective_key
                    and effective_key not in self._pending_queues):
                # User switched to a different session - trigger memory update for previous
                await self._on_session_inactive(self._last_active_session_key)

            # Compute the effective session key before dispatching
            # This ensures /stop command can find tasks correctly when unified session is enabled
            task = asyncio.create_task(self._dispatch(msg))
            self._last_active_session_key = effective_key
            self._active_tasks.setdefault(effective_key, []).append(task)
            task.add_done_callback(
                lambda t, k=effective_key: self._active_tasks.get(k, [])
                and self._active_tasks[k].remove(t)
                if t in self._active_tasks.get(k, [])
                else None
            )

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message: per-session serial, cross-session concurrent."""
        session_key = self._effective_session_key(msg)
        if session_key != msg.session_key:
            msg = dataclasses.replace(msg, session_key_override=session_key)
        lock = self._session_locks.setdefault(session_key, asyncio.Lock())
        gate = self._concurrency_gate or nullcontext()

        # Register a pending queue so follow-up messages for this session are
        # routed here (mid-turn injection) instead of spawning a new task.
        pending = asyncio.Queue(maxsize=20)
        self._pending_queues[session_key] = pending

        try:
            async with lock, gate:
                try:
                    on_stream = on_stream_end = None
                    if msg.metadata.get("_wants_stream"):
                        # Split one answer into distinct stream segments.
                        stream_base_id = f"{msg.session_key}:{time.time_ns()}"
                        stream_segment = 0

                        def _current_stream_id() -> str:
                            return f"{stream_base_id}:{stream_segment}"

                        async def on_stream(delta: str) -> None:
                            meta = dict(msg.metadata or {})
                            meta["_stream_delta"] = True
                            meta["_stream_id"] = _current_stream_id()
                            await self.bus.publish_outbound(OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content=delta,
                                metadata=meta,
                            ))

                        async def on_stream_end(*, resuming: bool = False) -> None:
                            nonlocal stream_segment
                            meta = dict(msg.metadata or {})
                            meta["_stream_end"] = True
                            meta["_resuming"] = resuming
                            meta["_stream_id"] = _current_stream_id()
                            await self.bus.publish_outbound(OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="",
                                metadata=meta,
                            ))
                            stream_segment += 1

                    response = await self._process_message(
                        msg, on_stream=on_stream, on_stream_end=on_stream_end,
                        pending_queue=pending,
                    )
                    if response is not None:
                        await self.bus.publish_outbound(response)
                    elif msg.channel == "cli":
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id,
                            content="", metadata=msg.metadata or {},
                        ))
                    if msg.channel == "websocket":
                        turn_lat = self._pending_turn_latency_ms.pop(session_key, None)
                        await self._webui_turns.handle_turn_end(
                            msg,
                            session_key=session_key,
                            latency_ms=turn_lat,
                        )
                except asyncio.CancelledError:
                    logger.info("Task cancelled for session {}", session_key)
                    # Preserve partial context from the interrupted turn so
                    # the user does not lose tool results and assistant
                    # messages accumulated before /stop.  The checkpoint was
                    # already persisted to session metadata by
                    # _emit_checkpoint during tool execution; materializing
                    # it into session history now makes it visible in the
                    # next conversation turn.
                    try:
                        key = self._effective_session_key(msg)
                        session = self.sessions.get_or_create(key)
                        if self._restore_runtime_checkpoint(session):
                            self._clear_pending_user_turn(session)
                            self.sessions.save(session)
                            logger.info(
                                "Restored partial context for cancelled session {}",
                                key,
                            )
                    except Exception:
                        logger.debug(
                            "Could not restore checkpoint for cancelled session {}",
                            session_key,
                            exc_info=True,
                        )
                    raise
                except Exception:
                    logger.exception("Error processing message for session {}", session_key)
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="Sorry, I encountered an error.",
                    ))
        finally:
            # Drain any messages still in the pending queue and re-publish
            # them to the bus so they are processed as fresh inbound messages
            # rather than silently lost.
            queue = self._pending_queues.pop(session_key, None)
            if queue is not None:
                leftover = 0
                while True:
                    try:
                        item = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    await self.bus.publish_inbound(item)
                    leftover += 1
                if leftover:
                    logger.info(
                        "Re-published {} leftover message(s) to bus for session {}",
                        leftover, session_key,
                    )
            await self._webui_turns.publish_run_status(msg, "idle")
            self._pending_turn_latency_ms.pop(session_key, None)
            self._webui_turns.discard(session_key)

    async def close_mcp(self) -> None:
        """Drain pending background archives, then close MCP connections."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        for name, stack in self._mcp_stacks.items():
            try:
                await stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                logger.debug("MCP server '{}' cleanup error (can be ignored)", name)
        self._mcp_stacks.clear()

    def _schedule_background(self, coro) -> None:
        """Schedule a coroutine as a tracked background task (drained on shutdown)."""
        task = asyncio.create_task(coro)
        self._background_tasks.append(task)
        task.add_done_callback(self._background_tasks.remove)

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_system_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        pending_queue: asyncio.Queue | None = None,
    ) -> OutboundMessage | None:
        """Process a system inbound message (e.g. subagent announce)."""
        channel, chat_id = (
            msg.chat_id.split(":", 1) if ":" in msg.chat_id else ("cli", msg.chat_id)
        )
        logger.info("Processing system message from {}", msg.sender_id)
        key = msg.session_key_override or f"{channel}:{chat_id}"
        session = self.sessions.get_or_create(key)
        if self._restore_runtime_checkpoint(session):
            self.sessions.save(session)
        if self._restore_pending_user_turn(session):
            self.sessions.save(session)

        session, pending = self.auto_compact.prepare_session(session, key)
        if pending:
            logger.info("Memory compact triggered for session {}", key)

        await self.consolidator.maybe_consolidate_by_tokens(
            session,
            replay_max_messages=self._max_messages,
        )
        is_subagent = msg.sender_id == "subagent"
        if is_subagent and self._persist_subagent_followup(session, msg):
            logger.debug("Subagent result persisted for session {}", key)
            self.sessions.save(session)
        self._set_tool_context(
            channel, chat_id, msg.metadata.get("message_id"),
            msg.metadata, session_key=key,
        )
        _hist_kwargs: dict[str, Any] = {
            "max_messages": self._max_messages,
            "max_tokens": self._replay_token_budget(),
            "include_timestamps": True,
        }
        history = session.get_history(**_hist_kwargs)
        current_role = "assistant" if is_subagent else "user"

        session_notes = self.sessions.get_session_notes(key)
        session_dir = str(self.sessions._get_session_dir(key))
        mode = session.metadata.get("mode")
        messages = self.context.build_messages(
            history=history,
            current_message="" if is_subagent else msg.content,
            channel=channel,
            chat_id=chat_id,
            current_role=current_role,
            sender_id=msg.sender_id,
            session_summary=pending,
            session_notes=session_notes,
            session_dir=session_dir,
            session_metadata=session.metadata,
            mode=mode,
        )
        t_wall = time.time()
        final_content, _, all_msgs, stop_reason, _ = await self._run_agent_loop(
            messages, session=session, channel=channel, chat_id=chat_id,
            message_id=msg.metadata.get("message_id"),
            metadata=msg.metadata,
            session_key=key,
            pending_queue=pending_queue,
        )
        wall_done = time.time()
        latency_ms = max(0, int((wall_done - t_wall) * 1000))
        self._save_turn(session, all_msgs, 1 + len(history), turn_latency_ms=latency_ms)
        if channel == "websocket":
            self._pending_turn_latency_ms[key] = latency_ms
        session.enforce_file_cap(on_archive=self.context.memory.raw_archive)
        self._clear_runtime_checkpoint(session)
        self.sessions.save(session)
        self._schedule_background(
            self.consolidator.maybe_consolidate_by_tokens(
                session,
                replay_max_messages=self._max_messages,
            )
        )
        content = final_content or "Background task completed."
        outbound_metadata: dict[str, Any] = {}
        if channel == "slack" and key.startswith("slack:") and key.count(":") >= 2:
            outbound_metadata["slack"] = {"thread_ts": key.split(":", 2)[2]}
        if origin_message_id := msg.metadata.get("origin_message_id"):
            outbound_metadata["origin_message_id"] = origin_message_id
        return OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            metadata=outbound_metadata,
        )

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        pending_queue: asyncio.Queue | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        self._refresh_provider_snapshot()

        if msg.channel == "system":
            return await self._process_system_message(
                msg,
                session_key=session_key,
                on_progress=on_progress,
                on_stream=on_stream,
                on_stream_end=on_stream_end,
                pending_queue=pending_queue,
            )

        key = session_key or msg.session_key
        ctx = TurnContext(
            msg=msg,
            session=None,
            session_key=key,
            state=TurnState.RESTORE,
            turn_id=f"{key}:{time.time_ns()}",
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            pending_queue=pending_queue,
        )

        while ctx.state is not TurnState.DONE:
            handler_name = f"_state_{ctx.state.name.lower()}"
            handler = getattr(self, handler_name, None)
            if handler is None:
                raise RuntimeError(f"Missing state handler for {ctx.state}")

            t0 = time.perf_counter()
            try:
                event = await handler(ctx)
            except Exception:
                duration = (time.perf_counter() - t0) * 1000
                ctx.trace.append(
                    StateTraceEntry(
                        state=ctx.state,
                        started_at=t0,
                        duration_ms=duration,
                        event="",
                        error="exception",
                    )
                )
                raise

            duration = (time.perf_counter() - t0) * 1000
            ctx.trace.append(
                StateTraceEntry(
                    state=ctx.state,
                    started_at=t0,
                    duration_ms=duration,
                    event=event,
                )
            )
            logger.debug(
                "[turn {}] State {} took {:.1f}ms -> event {}",
                ctx.turn_id,
                ctx.state.name,
                duration,
                event,
            )

            next_state = self._TRANSITIONS.get((ctx.state, event))
            if next_state is None:
                raise RuntimeError(
                    f"[turn {ctx.turn_id}] No transition from {ctx.state} "
                    f"on event {event!r}"
                )
            ctx.state = next_state

        logger.debug(
            "[turn {}] Turn completed after {} states",
            ctx.turn_id,
            len(ctx.trace),
        )

        # After a successful turn, bump counter and evaluate count-based triggers
        if ctx.session is not None:
            await self._maybe_spawn_periodic_subagents(ctx.session, ctx.msg)

        # Check notes AI queue after each turn
        await self._check_notes_ai_queue()

        return ctx.outbound

    def _assemble_outbound(
        self,
        msg: InboundMessage,
        final_content: str,
        all_msgs: list[dict[str, Any]],
        stop_reason: str,
        had_injections: bool,
        generated_media: list[str],
        on_stream: Callable[[str], Awaitable[None]] | None,
        *,
        turn_latency_ms: int | None = None,
    ) -> OutboundMessage | None:
        """Assemble the final outbound message from turn results."""
        # MessageTool suppression
        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            if not had_injections or stop_reason == "empty_final_response":
                return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        meta = dict(msg.metadata or {})
        if on_stream is not None and stop_reason not in {"error", "tool_error"}:
            meta["_streamed"] = True
        if turn_latency_ms is not None:
            meta["latency_ms"] = int(turn_latency_ms)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            media=generated_media,
            metadata=meta,
        )

    async def _state_restore(self, ctx: TurnContext) -> TurnState:
        """Restore checkpoint / pending user turn; extract documents."""
        msg = ctx.msg

        if msg.media:
            new_content, image_only = extract_documents(msg.content, msg.media)
            ctx.msg = dataclasses.replace(msg, content=new_content, media=image_only)
            msg = ctx.msg

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        # Session is already fetched by the caller (_process_message) but
        # ensure it exists in case this handler is invoked independently.
        if ctx.session is None:
            ctx.session = self.sessions.get_or_create(ctx.session_key)
        mark_webui_session(ctx.session, msg.metadata)

        if self._restore_runtime_checkpoint(ctx.session):
            self.sessions.save(ctx.session)
        if self._restore_pending_user_turn(ctx.session):
            self.sessions.save(ctx.session)

        # Ensure session title is set on first real user message
        await self._apply_session_title(ctx.session, msg)

        return "ok"

    async def _maybe_spawn_periodic_subagents(self, session: Session, msg: InboundMessage) -> None:
        """Spawn subagents based on counter trigger configuration.

        Called after a turn completes so only successful full conversations count.
        """
        # Skip on /freechat command - subagents should only run on real conversation turns
        raw = msg.content.strip().lower()
        if raw == "/freechat":
            return

        self.counter_engine.ensure_mode(session.metadata.get("mode"))
        self.counter_engine.increment_turn(session.metadata)
        session_dir = str(self.sessions._get_session_dir(session.key))
        turn_count = self.counter_engine.get_turn_count(session.metadata)

        if self._should_sync_wiki(turn_count, session.metadata.get("mode")):
            self._schedule_background(
                self._sync_wiki_for_session(session, session_dir)
            )

        triggers = self.counter_engine.check_triggers(session.metadata)

        if not triggers:
            return

        for trigger in triggers:
            self._schedule_background(
                self._spawn_counter_subagent(session, msg, trigger, session_dir)
            )

    def _should_sync_wiki(self, turn_count: int, mode: str | None = None) -> bool:
        """Return whether wiki sync should run after this completed user turn."""
        interval = wiki_sync_interval(self.counter_engine.workspace)
        if interval <= 0:
            return False
        if not isinstance(turn_count, int):
            return False
        if not wiki_mode_allowed(mode, self.counter_engine.workspace):
            return False
        return turn_count > 0 and turn_count % interval == 0

    async def _sync_wiki_for_session(
        self,
        session: Session,
        session_dir: str,
    ) -> None:
        """Background task: sync session conversation to wiki."""
        try:
            from nanobot.agent.wiki_sync import sync_session_to_wiki

            await sync_session_to_wiki(
                session_key=session.session_uuid or session.key,
                session_dir=session_dir,
                workspace=Path(self.counter_engine.workspace),
                provider=self.provider,
                model=self.model,
            )
        except Exception as e:
            logger.debug("Wiki sync background task failed: {}", e)

    async def _check_notes_ai_queue(self) -> None:
        """Check and process notes AI reply queue.

        Reads pending tasks from user-notes/.notes_ai_queue.json and spawns
        subagents to generate AI replies for each task.
        """
        import json

        try:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            queue_file = project_root / "user-notes" / ".notes_ai_queue.json"

            if not queue_file.exists():
                return

            try:
                queue_data = json.loads(queue_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError):
                return

            tasks = queue_data.get("tasks", [])
            if not tasks:
                return

            # Process pending tasks
            updated_tasks = []
            for task_item in tasks:
                if task_item.get("status") != "pending":
                    updated_tasks.append(task_item)
                    continue

                # Spawn subagent for this task
                task_id = task_item.get("task_id")
                note_id = task_item.get("note_id")
                date = task_item.get("date")
                reply_type = task_item.get("reply_type", "encouragement")
                note_content = task_item.get("note_content", "")
                quoted_content = task_item.get("quoted_content")

                logger.info(f"[NotesAI] Processing task {task_id} for note {note_id}")

                try:
                    # Read the subagent definition
                    subagent_file = project_root / "subagent" / "cross_session" / "notes_ai_assistant" / "context" / "notes_ai_assistant_subagent.md"
                    if not subagent_file.exists():
                        logger.warning("[NotesAI] Subagent definition not found")
                        task_item["status"] = "error"
                        task_item["error"] = "Subagent definition not found"
                        updated_tasks.append(task_item)
                        continue

                    subagent_content = subagent_file.read_text()
                    # Replace {{ workspace }} in subagent definition with project root
                    # (where user-notes/ directory lives), not the agent workspace
                    project_root = Path(__file__).resolve().parent.parent.parent.parent
                    subagent_content = subagent_content.replace("{{ workspace }}", str(project_root))

                    # Build context with note data
                    quoted_section = ""
                    if quoted_content:
                        quoted_section = f"Original Quoted Content:\n{quoted_content}\n\n"

                    note_context = f"""# Input Data for AI Reply Generation

Note ID: {note_id}
Date: {date}
Reply Type: {reply_type}

Note Content:
{note_content}

{quoted_section}---
"""

                    # Task is the note context, extra_system_prompt is the subagent definition
                    # (same pattern as memory subagent)
                    task_prompt = "Generate AI reply for this note and save to files using write_file tool."
                    extra_prompt = note_context + subagent_content

                    # Spawn the subagent
                    # Use "websocket" as origin_channel (a valid registered channel)
                    # since announce_result=False means no message will actually be sent
                    task_id_result = await self.subagents.spawn(
                        task=task_prompt,
                        label="AI Reply for note",
                        origin_channel="websocket",
                        origin_chat_id=f"notes-ai:{note_id}",
                        session_key="notes-ai:direct",
                        announce_result=False,
                        extra_system_prompt=extra_prompt,
                    )

                    logger.info(f"[NotesAI] Spawned subagent for task {task_id}: {task_id_result[:8]}...")
                    task_item["status"] = "running"
                    task_item["result"] = {"task_id": task_id_result}
                    self._schedule_background(
                        self._finalize_notes_ai_task(queue_file, task_id, task_id_result)
                    )

                except Exception as e:
                    logger.warning(f"[NotesAI] Error processing task {task_id}: {e}")
                    task_item["status"] = "error"
                    task_item["error"] = str(e)

                updated_tasks.append(task_item)

            # Write back updated queue
            queue_data["tasks"] = updated_tasks
            queue_file.write_text(json.dumps(queue_data, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as e:
            logger.warning(f"[NotesAI] Error checking queue: {e}")

    async def _finalize_notes_ai_task(
        self,
        queue_file: Path,
        queue_task_id: str,
        subagent_task_id: str,
    ) -> None:
        """Mark a notes AI queue item done after its subagent actually finishes."""
        import json

        try:
            status = await self.subagents.wait_for_subagent(subagent_task_id)
            try:
                queue_data = json.loads(queue_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            changed = False
            for task_item in queue_data.get("tasks", []):
                if task_item.get("task_id") != queue_task_id:
                    continue
                task_item["status"] = "error" if status.error else "done"
                task_item["result"] = {
                    "task_id": subagent_task_id,
                    "reply": status.result,
                }
                if status.error:
                    task_item["error"] = status.error
                changed = True
                break
            if changed:
                queue_file.write_text(json.dumps(queue_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("Notes AI task finalize failed: {}", e)

    async def _state_compact(self, ctx: TurnContext) -> str:
        ctx.session, pending = self.auto_compact.prepare_session(ctx.session, ctx.session_key)
        ctx.pending_summary = pending
        return "ok"

    def _load_benative_pairs(self, article_id: str) -> list[dict[str, Any]]:
        pairs_file = self.sessions.sessions_dir.parent / "benative" / "pairs" / f"{article_id}.jsonl"
        pairs: list[dict[str, Any]] = []
        if not pairs_file.exists():
            return pairs
        for line in pairs_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                pairs.append(item)
        return pairs

    def _benative_progress_file(self, session: Session) -> Path:
        return self.sessions._get_session_dir(session.key) / "notes" / "benative_progress.json"

    def _try_handle_benative_practice_turn(self, ctx: TurnContext, raw: str) -> OutboundMessage | None:
        """Handle Be Native reconstruction turns without invoking the main LLM."""
        if ctx.session is None:
            return None
        if raw.startswith("/"):
            return None
        if ctx.session.metadata.get("mode") != "benative":
            return None

        progress_file = self._benative_progress_file(ctx.session)
        if not progress_file.exists():
            return None

        try:
            progress = json.loads(progress_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        article_id = str(
            progress.get("article_id")
            or ctx.session.metadata.get("benative_article_id")
            or ""
        ).strip()
        if not article_id:
            return None

        pairs = self._load_benative_pairs(article_id)
        total = len(pairs)
        current = int(progress.get("current_sentence", 0) or 0)
        if total <= 0:
            content = f"No sentence pairs were found for `{article_id}` yet."
        elif current >= total:
            content = (
                f"This article is already complete: {total}/{total} sentences.\n\n"
                "Use `/benative` to choose another article."
            )
        else:
            from datetime import datetime

            pair = pairs[current]
            sentence_index = int(pair.get("sentence_index", current) or current)
            zh = str(pair.get("zh", ""))
            standard_en = str(pair.get("en", ""))
            user_en = raw.strip()

            from nanobot.benative.events import (
                append_benative_response,
                refresh_benative_session_summary,
            )
            from subagent._shared.benative_schema import BenativeResponse

            session_uuid = ctx.session.session_uuid or ctx.session.key
            workspace = Path(self.counter_engine.workspace)
            append_benative_response(
                workspace,
                BenativeResponse(
                    session_uuid=session_uuid,
                    article_id=article_id,
                    sentence_index=sentence_index,
                    zh=zh,
                    standard_en=standard_en,
                    user_en=user_en,
                    timestamp=datetime.now().isoformat(),
                ),
            )
            self.sessions.append_mode_response(
                ctx.session,
                current + 1,
                article_id=article_id,
                sentence_index=sentence_index,
                zh=zh,
                standard_en=standard_en,
                user_en=user_en,
            )

            next_index = current + 1
            progress["current_sentence"] = next_index
            progress["total_sentences"] = total
            progress_file.write_text(
                json.dumps(progress, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            refresh_benative_session_summary(
                workspace,
                session_uuid,
                article_id=article_id,
                total_sentences=total,
                current_sentence=next_index,
            )

            if next_index < total:
                next_pair = pairs[next_index]
                content = (
                    f"Recorded sentence {next_index}/{total}.\n\n"
                    f"Sentence {next_index + 1}/{total}:\n"
                    f"{next_pair.get('zh', '')}\n\n"
                    "Please answer in natural English."
                )
            else:
                content = (
                    f"Recorded sentence {next_index}/{total}.\n\n"
                    "This article is complete. Your answers have been saved for "
                    "vocab, polisher, and review subagents."
                )

        ctx.user_persisted_early = self._persist_user_message_early(
            ctx.msg,
            ctx.session,
            _benative_practice=True,
        )
        ctx.session.add_message("assistant", content, _benative_practice=True)
        self.sessions.save(ctx.session)
        self._clear_pending_user_turn(ctx.session)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=content,
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    async def _state_command(self, ctx: TurnContext) -> str:
        raw = ctx.msg.content.strip()
        cmd_ctx = CommandContext(
            msg=ctx.msg, session=ctx.session, key=ctx.session_key, raw=raw, loop=self
        )
        result = await self.commands.dispatch(cmd_ctx)
        if result is not None:
            ctx.outbound = result
            # Shortcut commands skip BUILD and SAVE, so we must persist the
            # turn here so WebUI history hydration after _turn_end sees the
            # message.  Mark messages with _command so get_history can filter
            # them out of LLM context.  /new is excluded because it
            # intentionally clears the session.
            if raw.lower() != "/new":
                ctx.user_persisted_early = self._persist_user_message_early(
                    ctx.msg, ctx.session, _command=True
                )
                ctx.session.add_message(
                    "assistant", result.content, _command=True
                )
                self.sessions.save(ctx.session)
                self._clear_pending_user_turn(ctx.session)
            return "shortcut"
        if deterministic := self._try_handle_benative_practice_turn(ctx, raw):
            ctx.outbound = deterministic
            return "shortcut"
        return "dispatch"

    async def _state_build(self, ctx: TurnContext) -> str:
        await self.consolidator.maybe_consolidate_by_tokens(
            ctx.session,
            replay_max_messages=self._max_messages,
        )
        self._set_tool_context(
            ctx.msg.channel,
            ctx.msg.chat_id,
            ctx.msg.metadata.get("message_id"),
            ctx.msg.metadata,
            session_key=ctx.session_key,
        )
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        _hist_kwargs: dict[str, Any] = {
            "max_messages": self._max_messages,
            "max_tokens": self._replay_token_budget(),
            "include_timestamps": True,
        }
        ctx.history = ctx.session.get_history(**_hist_kwargs)
        self._webui_turns.capture_title_context(
            ctx.session_key,
            ctx.msg,
            self.llm_runtime(),
        )

        ctx.initial_messages = self._build_initial_messages(
            ctx.msg, ctx.session, ctx.history, ctx.pending_summary
        )
        ctx.user_persisted_early = self._persist_user_message_early(
            ctx.msg, ctx.session
        )
        logger.info(
            "_state_build: user_persisted_early={}, history_len={}, initial_messages_len={}",
            ctx.user_persisted_early, len(ctx.history), len(ctx.initial_messages),
        )

        if ctx.on_progress is None:
            ctx.on_progress = await self._build_bus_progress_callback(ctx.msg)
        if ctx.on_retry_wait is None:
            ctx.on_retry_wait = await self._build_retry_wait_callback(ctx.msg)

        return "ok"

    async def _state_run(self, ctx: TurnContext) -> str:
        await self._webui_turns.publish_run_status(ctx.msg, "running")
        result = await self._run_agent_loop(
            ctx.initial_messages,
            on_progress=ctx.on_progress,
            on_stream=ctx.on_stream,
            on_stream_end=ctx.on_stream_end,
            on_retry_wait=ctx.on_retry_wait,
            session=ctx.session,
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            message_id=ctx.msg.metadata.get("message_id"),
            metadata=ctx.msg.metadata,
            session_key=ctx.session_key,
            pending_queue=ctx.pending_queue,
        )
        final_content, tools_used, all_msgs, stop_reason, had_injections = result
        ctx.final_content = final_content
        ctx.tools_used = tools_used
        ctx.all_messages = all_msgs
        ctx.stop_reason = stop_reason
        ctx.had_injections = had_injections
        return "ok"

    async def _state_save(self, ctx: TurnContext) -> str:
        if ctx.final_content is None or not ctx.final_content.strip():
            ctx.final_content = EMPTY_FINAL_RESPONSE_MESSAGE

        ctx.save_skip = 1 + len(ctx.history) + (1 if ctx.user_persisted_early else 0)
        logger.info(
            "_state_save: save_skip={}, all_messages_len={}, history_len={}, user_persisted_early={}",
            ctx.save_skip, len(ctx.all_messages), len(ctx.history), ctx.user_persisted_early,
        )

        # When user message was persisted early, we still need to call append_user_expression
        # for it (the for loop below skips it via save_skip). Extract user content from
        # initial_messages (index 1 + len(history) = user message position).
        if ctx.user_persisted_early and ctx.initial_messages:
            user_msg_idx = 1 + len(ctx.history)
            if user_msg_idx < len(ctx.initial_messages):
                user_entry = ctx.initial_messages[user_msg_idx]
                if user_entry.get("role") == "user":
                    user_content = user_entry.get("content") or ""
                    if isinstance(user_content, list):
                        # Handle content blocks (e.g., text + image references)
                        user_content = " ".join(
                            b.get("text", "") for b in user_content if b.get("type") == "text"
                        )
                    self.sessions.append_user_expression(
                        ctx.session, ctx.session._current_round, user_content,
                    )

        skip_msgs = ctx.all_messages[ctx.save_skip:]
        ctx.generated_media = generated_image_paths_from_messages(skip_msgs)
        mt = self.tools.get("message")
        extra = getattr(mt, "turn_delivered_media_paths", lambda: [])() if mt else []
        merge_turn_media_into_last_assistant(ctx.all_messages, ctx.generated_media, extra)

        ctx.turn_latency_ms = max(0, int((time.time() - ctx.turn_wall_started_at) * 1000))
        self._save_turn(
            ctx.session, ctx.all_messages, ctx.save_skip,
            turn_latency_ms=ctx.turn_latency_ms,
        )
        if ctx.msg.channel == "websocket":
            self._pending_turn_latency_ms[ctx.session_key] = ctx.turn_latency_ms
        ctx.session.enforce_file_cap(on_archive=self.context.memory.raw_archive)
        self._clear_pending_user_turn(ctx.session)
        self._clear_runtime_checkpoint(ctx.session)
        self.sessions.save(ctx.session)
        self._schedule_background(
            self.consolidator.maybe_consolidate_by_tokens(
                ctx.session,
                replay_max_messages=self._max_messages,
            )
        )
        return "ok"

    async def _state_respond(self, ctx: TurnContext) -> str:
        ctx.outbound = self._assemble_outbound(
            ctx.msg,
            ctx.final_content,
            ctx.all_messages,
            ctx.stop_reason,
            ctx.had_injections,
            ctx.generated_media,
            ctx.on_stream,
            turn_latency_ms=ctx.turn_latency_ms,
        )
        return "ok"

    def _sanitize_persisted_blocks(
        self,
        content: list[dict[str, Any]],
        *,
        should_truncate_text: bool = False,
        drop_runtime: bool = False,
    ) -> list[dict[str, Any]]:
        """Strip volatile multimodal payloads before writing session history."""
        filtered: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                filtered.append(block)
                continue

            if (
                drop_runtime
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and block["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
            ):
                continue

            if block.get("type") == "image_url" and block.get("image_url", {}).get(
                "url", ""
            ).startswith("data:image/"):
                path = (block.get("_meta") or {}).get("path", "")
                filtered.append({"type": "text", "text": image_placeholder_text(path)})
                continue

            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                if should_truncate_text and len(text) > self.max_tool_result_chars:
                    text = truncate_text_fn(text, self.max_tool_result_chars)
                filtered.append({**block, "text": text})
                continue

            filtered.append(block)

        return filtered

    def _save_turn(
        self,
        session: Session,
        messages: list[dict],
        skip: int,
        *,
        turn_latency_ms: int | None = None,
    ) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime

        # Initialize round tracking: start from current session round
        current_round = session._current_round
        prev_role: str | None = None
        # Determine previous role from last saved message (if any)
        if session.messages:
            prev_role = session.messages[-1].get("role")

        last_assistant_idx: int | None = None
        logger.info(
            "_save_turn ENTRY: skip={}, messages_len={}, history_len={}, user_persisted_early={}",
            skip, len(messages), len(session.messages) if hasattr(session, 'messages') else 0,
            session._current_round if hasattr(session, '_current_round') else 0,
        )
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")

            # Increment round on role switch (user <-> assistant)
            if prev_role is not None and role != prev_role:
                current_round += 1
            prev_role = role

            logger.info(
                "_save_turn processing: role={}, content={}",
                role,
                str(content)[:50] if content else "",
            )

            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool":
                if isinstance(content, str) and len(content) > self.max_tool_result_chars:
                    entry["content"] = truncate_text_fn(content, self.max_tool_result_chars)
                elif isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, should_truncate_text=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            elif role == "user":
                if isinstance(content, str) and ContextBuilder._RUNTIME_CONTEXT_TAG in content:
                    # Strip the runtime-context block appended at the end.
                    tag_pos = content.find(ContextBuilder._RUNTIME_CONTEXT_TAG)
                    before = content[:tag_pos].rstrip("\n ")
                    if before:
                        entry["content"] = before
                    else:
                        continue
                if isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, drop_runtime=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
                # Skip round 0 — this is the implicit freechat prompt, not a real user reply
                if current_round > 0:
                    self.sessions.append_user_expression(session, current_round, entry["content"])
                logger.info(
                    "append_user_expression called: session={}, round={}, content_len={}",
                    session.key,
                    current_round,
                    len(entry["content"]) if isinstance(entry["content"], str) else 0,
                )
            entry.setdefault("timestamp", datetime.now().isoformat())
            entry["round"] = current_round
            session.messages.append(entry)
            if role == "assistant":
                last_assistant_idx = len(session.messages) - 1
        # Persist updated round to session
        session._current_round = current_round
        if turn_latency_ms is not None and last_assistant_idx is not None:
            session.messages[last_assistant_idx]["latency_ms"] = int(turn_latency_ms)
        session.updated_at = datetime.now()

    def _persist_subagent_followup(self, session: Session, msg: InboundMessage) -> bool:
        """Persist subagent follow-ups before prompt assembly so history stays durable.

        Returns True if a new entry was appended; False if the follow-up was
        deduped (same ``subagent_task_id`` already in session) or carries no
        content worth persisting.
        """
        if not msg.content:
            return False
        task_id = msg.metadata.get("subagent_task_id") if isinstance(msg.metadata, dict) else None
        if task_id and any(
            m.get("injected_event") == "subagent_result" and m.get("subagent_task_id") == task_id
            for m in session.messages
        ):
            return False
        session.add_message(
            "assistant",
            msg.content,
            sender_id=msg.sender_id,
            injected_event="subagent_result",
            subagent_task_id=task_id,
        )
        return True

    def _set_runtime_checkpoint(self, session: Session, payload: dict[str, Any]) -> None:
        """Persist the latest in-flight turn state into session metadata."""
        session.metadata[self._RUNTIME_CHECKPOINT_KEY] = payload
        self.sessions.save(session)

    def _mark_pending_user_turn(self, session: Session) -> None:
        session.metadata[self._PENDING_USER_TURN_KEY] = True

    def _clear_pending_user_turn(self, session: Session) -> None:
        session.metadata.pop(self._PENDING_USER_TURN_KEY, None)

    def _clear_runtime_checkpoint(self, session: Session) -> None:
        if self._RUNTIME_CHECKPOINT_KEY in session.metadata:
            session.metadata.pop(self._RUNTIME_CHECKPOINT_KEY, None)

    @staticmethod
    def _checkpoint_message_key(message: dict[str, Any]) -> tuple[Any, ...]:
        return (
            message.get("role"),
            message.get("content"),
            message.get("tool_call_id"),
            message.get("name"),
            message.get("tool_calls"),
            message.get("reasoning_content"),
            message.get("thinking_blocks"),
        )

    def _restore_runtime_checkpoint(self, session: Session) -> bool:
        """Materialize an unfinished turn into session history before a new request."""
        from datetime import datetime

        checkpoint = session.metadata.get(self._RUNTIME_CHECKPOINT_KEY)
        if not isinstance(checkpoint, dict):
            return False

        assistant_message = checkpoint.get("assistant_message")
        completed_tool_results = checkpoint.get("completed_tool_results") or []
        pending_tool_calls = checkpoint.get("pending_tool_calls") or []

        restored_messages: list[dict[str, Any]] = []
        if isinstance(assistant_message, dict):
            restored = dict(assistant_message)
            restored.setdefault("timestamp", datetime.now().isoformat())
            restored_messages.append(restored)
        for message in completed_tool_results:
            if isinstance(message, dict):
                restored = dict(message)
                restored.setdefault("timestamp", datetime.now().isoformat())
                restored_messages.append(restored)
        for tool_call in pending_tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_id = tool_call.get("id")
            name = ((tool_call.get("function") or {}).get("name")) or "tool"
            restored_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": name,
                    "content": "Error: Task interrupted before this tool finished.",
                    "timestamp": datetime.now().isoformat(),
                }
            )

        overlap = 0
        max_overlap = min(len(session.messages), len(restored_messages))
        for size in range(max_overlap, 0, -1):
            existing = session.messages[-size:]
            restored = restored_messages[:size]
            if all(
                self._checkpoint_message_key(left) == self._checkpoint_message_key(right)
                for left, right in zip(existing, restored)
            ):
                overlap = size
                break
        session.messages.extend(restored_messages[overlap:])

        self._clear_pending_user_turn(session)
        self._clear_runtime_checkpoint(session)
        return True

    def _restore_pending_user_turn(self, session: Session) -> bool:
        """Close a turn that only persisted the user message before crashing."""
        from datetime import datetime

        if not session.metadata.get(self._PENDING_USER_TURN_KEY):
            return False

        if session.messages and session.messages[-1].get("role") == "user":
            session.messages.append(
                {
                    "role": "assistant",
                    "content": "Error: Task interrupted before a response was generated.",
                    "timestamp": datetime.now().isoformat(),
                }
            )
            session.updated_at = datetime.now()

        self._clear_pending_user_turn(session)
        return True

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        media: list[str] | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a message directly and return the outbound payload."""
        await self._connect_mcp()
        msg = InboundMessage(
            channel=channel, sender_id="user", chat_id=chat_id,
            content=content, media=media or [],
        )
        return await self._process_message(
            msg,
            session_key=session_key,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
        )
