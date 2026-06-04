"""Read-only context tools for processor-mediated subagents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext, ToolContext
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema

_MAX_TEXT_CHARS = 24_000


def _read_text(path: Path, *, max_chars: int = _MAX_TEXT_CHARS) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


def _read_jsonl_tail(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(limit * 4, limit):]:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            value = {"raw": line}
        if isinstance(value, dict):
            rows.append(value)
        else:
            rows.append({"value": value})
    return rows[-limit:]


def _message_text(row: dict[str, Any]) -> str:
    content = row.get("content")
    if isinstance(content, dict):
        value = content.get("text")
        return value if isinstance(value, str) else json.dumps(content, ensure_ascii=False)
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False) if content is not None else ""


def _safe_workspace_path(workspace: Path, relative_path: str, *, allowed_prefixes: tuple[str, ...]) -> Path | None:
    raw = relative_path.strip()
    if not raw or Path(raw).is_absolute():
        return None
    normalized = Path(raw)
    candidate = (workspace / normalized).resolve()
    try:
        rel = candidate.relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return None
    if not any(rel == prefix.rstrip("/") for prefix in allowed_prefixes) and not rel.startswith(allowed_prefixes):
        return None
    return candidate


class _WorkspaceContextTool(Tool, ContextAware):
    _scopes = {"subagent"}

    def __init__(self, workspace: Path | str):
        self.workspace = Path(workspace).resolve()
        self._request_ctx: RequestContext | None = None

    @property
    def read_only(self) -> bool:
        return True

    def set_context(self, ctx: RequestContext) -> None:
        self._request_ctx = ctx


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema("Optional case-insensitive text filter", max_length=200),
        role=StringSchema("Message role filter", enum=("all", "user", "assistant")),
        limit=IntegerSchema(description="Maximum messages to return", minimum=1, maximum=50),
    )
)
class ThreadQueryTool(_WorkspaceContextTool):
    """Read recent conversation rows from the unified thread log."""

    name = "thread_query"
    description = "Read recent conversation turns from persona/events/thread.jsonl with optional role/query filtering."

    @classmethod
    def create(cls, ctx: ToolContext) -> "ThreadQueryTool":
        return cls(ctx.workspace)

    async def execute(
        self,
        query: str | None = None,
        role: str | None = "user",
        limit: int | None = 12,
    ) -> dict[str, Any]:
        path = self.workspace / "persona" / "events" / "thread.jsonl"
        rows = _read_jsonl_tail(path, limit=max(limit or 12, 1) * 4)
        needle = (query or "").strip().lower()
        role_filter = (role or "user").strip().lower()
        results: list[dict[str, Any]] = []
        for row in rows:
            row_role = str(row.get("role") or "")
            text = _message_text(row)
            if role_filter != "all" and row_role != role_filter:
                continue
            if needle and needle not in text.lower():
                continue
            source = row.get("source") if isinstance(row.get("source"), dict) else {}
            results.append(
                {
                    "id": row.get("id"),
                    "timestamp": row.get("timestamp"),
                    "role": row_role,
                    "mode": source.get("mode"),
                    "session_uuid": source.get("session_uuid"),
                    "message_index": source.get("message_index"),
                    "text": text[:2000],
                }
            )
        capped = results[-max(limit or 12, 1):]
        return {"status": "ok", "path": "persona/events/thread.jsonl", "count": len(capped), "messages": capped}


@tool_parameters(
    tool_parameters_schema(
        artifact=StringSchema("Known artifact name: vocab, polisher, notes, processor_runs, subagent_runs", max_length=80),
        path=StringSchema("Optional relative path under persona/processor or monitor", max_length=240),
        limit=IntegerSchema(description="Maximum JSONL rows to return", minimum=1, maximum=100),
    )
)
class ArtifactReadTool(_WorkspaceContextTool):
    """Read processor artifacts or monitor run logs."""

    name = "artifact_read"
    description = "Read recent rows from processor artifacts or monitor logs. This tool is read-only."

    _ARTIFACTS = {
        "vocab": "persona/processor/freechat/vocab.jsonl",
        "polisher": "persona/processor/freechat/polisher.jsonl",
        "notes": "persona/processor/freechat/notes.md",
        "processor_runs": "monitor/processor_runs.jsonl",
        "subagent_runs": "monitor/subagent_runs.jsonl",
    }

    @classmethod
    def create(cls, ctx: ToolContext) -> "ArtifactReadTool":
        return cls(ctx.workspace)

    async def execute(
        self,
        artifact: str | None = None,
        path: str | None = None,
        limit: int | None = 20,
    ) -> dict[str, Any]:
        rel = path or self._ARTIFACTS.get((artifact or "").strip(), "")
        target = _safe_workspace_path(
            self.workspace,
            rel,
            allowed_prefixes=("persona/processor/", "monitor/"),
        )
        if target is None:
            return {"status": "error", "message": "Unknown artifact or path outside allowed artifact roots."}
        if target.suffix == ".jsonl":
            rows = _read_jsonl_tail(target, limit=max(limit or 20, 1))
            return {"status": "ok", "path": target.relative_to(self.workspace).as_posix(), "rows": rows, "count": len(rows)}
        text = _read_text(target)
        return {"status": "ok", "path": target.relative_to(self.workspace).as_posix(), "content": text}


@tool_parameters(tool_parameters_schema(section=StringSchema("Optional section name hint", max_length=80)))
class UserProfileTool(_WorkspaceContextTool):
    """Read stable user profile and memory files."""

    name = "user_profile"
    description = "Read stable user profile and long-term memory files from persona/USER.md and persona/memory/MEMORY.md."

    @classmethod
    def create(cls, ctx: ToolContext) -> "UserProfileTool":
        return cls(ctx.workspace)

    async def execute(self, section: str | None = None) -> dict[str, Any]:
        files = {
            "user": self.workspace / "persona" / "USER.md",
            "memory": self.workspace / "persona" / "memory" / "MEMORY.md",
        }
        data = {name: _read_text(path) for name, path in files.items()}
        hint = (section or "").strip().lower()
        if hint:
            data = {name: text for name, text in data.items() if hint in text.lower()}
        return {"status": "ok", "files": data}


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema("Wiki search query", max_length=300),
        mode=StringSchema("Optional mode filter", max_length=50),
        topic=StringSchema("Optional topic filter", max_length=100),
        page_type=StringSchema("Optional page type filter", max_length=80),
        limit=IntegerSchema(description="Maximum results", minimum=1, maximum=20),
    )
)
class WikiQueryTool(_WorkspaceContextTool):
    """Search LLM Wiki pages using the project wiki query engine."""

    name = "wiki_query"
    description = "Search LLM Wiki pages, entities, concepts, and topics. Read-only."

    @classmethod
    def create(cls, ctx: ToolContext) -> "WikiQueryTool":
        return cls(ctx.workspace)

    async def execute(
        self,
        query: str | None = None,
        mode: str | None = None,
        topic: str | None = None,
        page_type: str | None = None,
        limit: int | None = 8,
    ) -> dict[str, Any]:
        wiki_root = self.workspace / "persona" / "wiki"
        try:
            from subagent.cross_session.wiki.processor.wiki_query import WikiQueryEngine

            results = WikiQueryEngine(wiki_root=wiki_root).query(
                query=query or "",
                mode=mode,
                topic=topic,
                page_type=page_type,
                limit=limit or 8,
            )
            return {
                "status": "ok",
                "count": len(results),
                "results": [item.model_dump() for item in results],
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
