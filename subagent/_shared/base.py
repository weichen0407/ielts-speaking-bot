"""Base class for all Data Processors."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, TypeVar

import json

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
U = TypeVar("U", bound=BaseModel)


class BaseDataProcessor(ABC, Generic[T, U]):
    """
    DataProcessor 基类

    定义通用流程：
    1. read()        - 读取 thread.jsonl
    2. preprocess()  - 预处理（去无用字段，过滤）
    3. build_prompt()- 组装 prompt
    4. call_llm()   - 调用 LLM
    5. parse_output()- 解析 LLM 输出
    6. serialize()   - 写回 jsonl 或生成 md

    子类必须实现：
    - name 属性      - 唯一标识
    - get_input_schema()  - 返回输入 Schema
    - get_output_schema() - 返回输出 Schema
    - build_user_prompt() - 组装用户 prompt
    - parse_llm_output()  - 解析 LLM 输出
    """

    name: str = "base"

    @abstractmethod
    def get_input_schema(self) -> type[T]:
        """子类返回输入 Schema"""
        pass

    @abstractmethod
    def get_output_schema(self) -> type[U]:
        """子类返回输出 Schema"""
        pass

    @abstractmethod
    def build_user_prompt(self, data: list[T]) -> str:
        """子类实现具体的 prompt 组装逻辑"""
        pass

    @abstractmethod
    def parse_llm_output(self, raw_output: str) -> list[U]:
        """子类实现 LLM 输出的解析逻辑"""
        pass

    def read(self, path: Path) -> list[dict]:
        """读取 jsonl，返回原始 dict 列表"""
        with open(path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def preprocess(self, raw_data: list[dict]) -> list[T]:
        """
        预处理：
        1. 过滤无用字段（id, ts, _type 等）
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
        """过滤通用字段，子类可 override"""
        excluded = {"id", "timestamp", "source", "metadata"}
        result = {}
        for k, v in item.items():
            if k in excluded:
                if k == "source" and isinstance(v, dict):
                    result["mode"] = v.get("mode")
                elif k == "metadata" and isinstance(v, dict):
                    result["topic"] = v.get("topic")
                continue
            if k == "content" and isinstance(v, dict):
                result[k] = v.get("text", "")
            elif k == "content" and isinstance(v, str):
                result[k] = v
            else:
                result[k] = v
        return result

    def process_all(
        self,
        input_path: Path,
        output_path: Path,
        batch_size: int = 50,
        format: str = "jsonl",
    ):
        """处理所有批次"""
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

    def serialize(
        self,
        data: list[U],
        output_path: Path,
        format: str = "jsonl",
    ):
        """序列化输出"""
        if format == "jsonl":
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "a", encoding="utf-8") as f:
                for item in data:
                    f.write(item.model_dump_json() + "\n")
        elif format == "md":
            self._serialize_md(data, output_path)

    def _serialize_md(self, data: list[U], path: Path):
        """生成 markdown，子类可 override"""
        lines = ["# Output\n"]
        for item in data:
            lines.append(f"- {item.model_dump()}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def get_system_prompt(self) -> str:
        """默认 system prompt，子类可 override"""
        return "You are a data processing expert."

    def _call_llm(self, system: str, user: str) -> str:
        """
        调用 LLM via SubagentManager
        子类可 override 以更换实现
        """
        raise NotImplementedError(
            f"{self.name} processor does not implement _call_llm()"
        )
