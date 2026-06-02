"""Base class for all Data Processors."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Generic, TypeVar

import json

from pydantic import BaseModel

from .utils import ensure_output_dir

T = TypeVar("T", bound=BaseModel)
U = TypeVar("U", bound=BaseModel)


class BaseDataProcessor(ABC, Generic[T, U]):
    """
    DataProcessor 基类

    定义通用流程：
    1. read()         - 读取 thread.jsonl
    2. preprocess()    - 预处理（提取有用字段，减少 token）
    3. build_prompt() - 组装 prompt 给 LLM
    4. call_llm()     - 调用 LLM
    5. parse_llm_output() - 解析 LLM 输出（第二工程层）
    6. serialize()     - 写回 jsonl 和生成 md

    子类必须实现：
    - name 属性           - 唯一标识
    - get_input_schema()  - 返回输入 Schema
    - get_output_schema() - 返回输出 Schema（告诉 LLM 几个字段）
    - build_user_prompt() - 组装用户 prompt
    - parse_llm_output()  - 解析 LLM tab 分隔的输出
    - to_md()            - 生成 md 格式报告
    """

    name: str = "base"

    def __init__(self) -> None:
        self._llm_caller: Callable[[str, str], Awaitable[str]] | None = None
        self._usage_total: dict[str, int] = {}

    @abstractmethod
    def get_input_schema(self) -> type[T]:
        """子类返回输入 Schema"""
        pass

    @abstractmethod
    def get_output_schema(self) -> type[U]:
        """子类返回输出 Schema（字段名列表，用于 parse）"""
        pass

    @abstractmethod
    def build_user_prompt(self, data: list[T]) -> str:
        """子类实现具体的 prompt 组装逻辑"""
        pass

    @abstractmethod
    def parse_llm_output(self, raw_output: str) -> list[U]:
        """子类实现 LLM 输出的解析逻辑（第二工程层）"""
        pass

    @abstractmethod
    def to_md(self, parsed_data: list[U]) -> str:
        """子类实现 md 格式输出"""
        pass

    def read(self, path: Path) -> list[dict]:
        """读取 jsonl，返回原始 dict 列表"""
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def configure_llm(
        self,
        *,
        provider: Any,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        retry_mode: str = "standard",
    ) -> None:
        """Bind the active nanobot provider/model to this processor.

        Processors keep the learning-task flow local, while the runtime owns
        provider configuration and API credentials.
        """

        async def _caller(system: str, user: str) -> str:
            response = await provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                tools=None,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                retry_mode=retry_mode,
            )
            if response.finish_reason == "error":
                raise RuntimeError(response.content or "LLM processor call failed")
            for key, value in (response.usage or {}).items():
                try:
                    self._usage_total[key] = self._usage_total.get(key, 0) + int(value)
                except (TypeError, ValueError):
                    continue
            return response.content or ""

        self._llm_caller = _caller

    def get_usage(self) -> dict[str, int]:
        """Return accumulated LLM token usage for this processor run."""
        return dict(self._usage_total)

    def preprocess(self, raw_data: list[dict]) -> list[T]:
        """
        预处理（第一工程层）：
        1. 提取有用字段（保留 id、content、topic 等）
        2. 验证 schema
        3. 返回 Pydantic 模型列表
        """
        schema = self.get_input_schema()
        processed = []
        for item in raw_data:
            filtered = self._filter_fields(item)
            try:
                processed.append(schema(**filtered))
            except Exception:
                continue
        return processed

    def _filter_fields(self, item: dict) -> dict:
        """
        过滤字段，保留子类 input schema 需要的字段供 LLM 使用。

        普通 thread 事件里的字段可能嵌套在 content/source/metadata 中；
        二级 artifact processor 的字段通常直接在顶层。这里优先保留
        schema 声明的顶层字段，再兼容 thread 特殊结构。
        子类可 override
        """
        wanted = set(self.get_input_schema().model_fields.keys())
        result = {key: item[key] for key in wanted if key in item}

        if "content" in wanted and "content" in item:
            content = item["content"]
            if isinstance(content, dict):
                result["content"] = content.get("text", "")
            elif isinstance(content, str):
                result["content"] = content

        if "metadata" in item and isinstance(item["metadata"], dict):
            topic = item["metadata"].get("topic")
            mode = item["metadata"].get("mode")
            if "topic" in wanted and "topic" not in result and topic is not None:
                result["topic"] = topic
            if "mode" in wanted and "mode" not in result and mode is not None:
                result["mode"] = mode

        if "source" in item and isinstance(item["source"], dict):
            mode = item["source"].get("mode")
            session_uuid = item["source"].get("session_uuid")
            message_index = item["source"].get("message_index")
            if "mode" in wanted and "mode" not in result and mode is not None:
                result["mode"] = mode
            if "session_uuid" in wanted and session_uuid is not None:
                result["session_uuid"] = session_uuid
            if "message_index" in wanted and message_index is not None:
                result["message_index"] = message_index
        return result

    def process_all(
        self,
        input_path: Path,
        output_path: Path,
        batch_size: int = 50,
        format: str = "both",
    ):
        """
        处理所有批次

        Args:
            input_path: thread.jsonl 路径
            output_path: 输出路径（jsonl 时用）
            batch_size: 每批处理多少条
            format: "jsonl" | "md" | "both"
        """
        all_data = self.read(input_path)
        total = len(all_data)

        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch = all_data[start:end]

            processed = self.preprocess(batch)
            if not processed:
                continue

            user_prompt = self.build_user_prompt(processed)
            system_prompt = self.get_system_prompt()

            raw_output = self._call_llm(system_prompt, user_prompt)
            if not raw_output:
                continue

            parsed = self.parse_llm_output(raw_output)
            if parsed:
                self.serialize(parsed, output_path, format)

    async def aprocess_all(
        self,
        input_path: Path,
        output_path: Path,
        batch_size: int = 50,
        format: str = "both",
    ):
        """
        Async version of process_all for nanobot runtime execution.

        AgentLoop already runs inside an event loop, so processor LLM calls must
        be awaited instead of using asyncio.run() from inside process_all().
        """
        all_data = self.read(input_path)
        total = len(all_data)

        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch = all_data[start:end]

            processed = self.preprocess(batch)
            if not processed:
                continue

            user_prompt = self.build_user_prompt(processed)
            system_prompt = self.get_system_prompt()

            raw_output = await self._acall_llm(system_prompt, user_prompt)
            if not raw_output:
                continue

            parsed = self.parse_llm_output(raw_output)
            if parsed:
                self.serialize(parsed, output_path, format)

    def serialize(
        self,
        data: list[U],
        output_path: Path,
        format: str = "both",
    ):
        """
        序列化输出

        Args:
            data: parse 后的 Pydantic 模型列表
            output_path: jsonl 输出路径（md 路径自动推导）
            format: "jsonl" | "md" | "both"
        """
        if format in ("jsonl", "both"):
            self._serialize_jsonl(data, output_path)

        if format in ("md", "both"):
            md_path = output_path.with_suffix(".md")
            md_content = self.to_md(data)
            ensure_output_dir(md_path)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)

    def _serialize_jsonl(self, data: list[U], path: Path) -> None:
        """追加写入 jsonl"""
        ensure_output_dir(path)
        with open(path, "a", encoding="utf-8") as f:
            for item in data:
                f.write(item.model_dump_json() + "\n")

    def get_system_prompt(self) -> str:
        """默认 system prompt，子类可 override"""
        return "You are a data processing expert."

    def _call_llm(self, system: str, user: str) -> str:
        """
        调用 LLM via SubagentManager
        子类可 override 以更换实现
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._acall_llm(system, user))
        raise RuntimeError(
            f"{self.name} processor is running inside an event loop; "
            "use aprocess_all() instead of process_all()."
        )

    async def _acall_llm(self, system: str, user: str) -> str:
        """Call the configured LLM runtime."""
        if self._llm_caller is None:
            raise RuntimeError(
                f"{self.name} processor has no LLM runtime configured. "
                "Call configure_llm() before running it."
            )
        return await self._llm_caller(system, user)
