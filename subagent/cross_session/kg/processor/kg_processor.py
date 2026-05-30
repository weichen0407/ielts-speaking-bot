"""KGProcessor - builds knowledge graph from Level 2 processed files.

DEPRECATED: Use subagent.cross_session.wiki.processor.wiki_processor instead."""

from pathlib import Path

from subagent._shared.base import BaseDataProcessor
from subagent._shared.utils import parse_tab_line
from .schema import KGInput, KGOutput
from .entity_store import EntityStore


class KGProcessor(BaseDataProcessor[KGInput, KGOutput]):
    """KG 处理器 - 从 Level 2 文件构建知识图谱"""

    name = "kg"

    def get_input_schema(self) -> type[KGInput]:
        return KGInput

    def get_output_schema(self) -> type[KGOutput]:
        return KGOutput

    def get_system_prompt(self) -> str:
        return r"""You are a knowledge graph builder.
Given content from Level 2 processed files (vocab, polisher, notes), extract entities and relations.
Output format: tab-separated fields, one per line.

For ENTITIES (one per line):
{label}	{entity_type}	{topics}

For RELATIONS (one per line):
{from_entity}	{to_entity}	{relation_type}	{topics}

Entity types: person, activity, object, place, event, food, hobby, occupation, emotion, opinion
Relation types: likes, related_to, part_of, location_of, uses, etc.
Topics: sports, food, hobbies, family, travel, work, education, technology, environment, culture, etc.

Example:
I	person	sports,hobbies
basketball	activity	sports
be fond of	emotion	hobbies
I-like-basketball	basketball	likes	sports

If no content to process, output (none)."""

    def build_user_prompt(self, data: list[KGInput]) -> str:
        lines = []
        for item in data:
            source = f"[{item.source}]" if item.source else ""
            lines.append(f"{source} {item.content}")
        return "\n".join(lines)

    def parse_llm_output(self, raw_output: str) -> list[KGOutput]:
        """解析 LLM 输出（第二工程层）"""
        results = []
        for line in raw_output.strip().split("\n"):
            line = line.strip()
            if not line or line == "(none)":
                continue

            parts = line.split("\t")
            if len(parts) >= 3:
                # Could be entity or relation
                first = parts[0]
                second = parts[1]

                # Check if it's a relation (3-4 parts with relation format)
                # Relation format: from_entity	to_entity	relation_type	topics
                if len(parts) >= 4 and "-" in first:
                    # This looks like a relation from_label-to_label
                    output = KGOutput(
                        from_label=parts[0],
                        to_label=parts[1],
                        relation_type=parts[2],
                        topics=parts[3] if len(parts) > 3 else None,
                        topics_list=self._parse_topics(parts[3] if len(parts) > 3 else ""),
                    )
                    results.append(output)
                elif len(parts) >= 3:
                    # Likely an entity: label	type	topics
                    output = KGOutput(
                        label=parts[0],
                        entity_type=parts[1],
                        topics=parts[2] if len(parts) > 2 else None,
                        topics_list=self._parse_topics(parts[2] if len(parts) > 2 else ""),
                    )
                    results.append(output)
        return results

    def _parse_topics(self, topics_str: str) -> list[str]:
        """Parse comma-separated topics string."""
        if not topics_str:
            return []
        return [t.strip() for t in topics_str.split(",") if t.strip()]

    def to_md(self, parsed_data: list[KGOutput]) -> str:
        """KG 不需要 MD 输出（是结构化数据）"""
        return ""

    def process_all(
        self,
        input_paths: list[Path],
        output_path: Path,
        batch_size: int = 50,
        format: str = "json",
    ):
        """
        处理所有 Level 2 文件，构建知识图谱

        Args:
            input_paths: Level 2 文件路径列表
            output_path: entity_database.json 输出路径
            batch_size: 每批处理条数
            format: 输出格式（只用 json）
        """
        from .entity_store import EntityStore

        # Collect all data from input files
        all_data = []
        for input_path in input_paths:
            if input_path.exists():
                file_data = self.read(input_path)
                all_data.extend(file_data)

        if not all_data:
            return

        # Preprocess
        processed = self.preprocess(all_data)
        if not processed:
            return

        # Build prompt and call LLM
        user_prompt = self.build_user_prompt(processed)
        system_prompt = self.get_system_prompt()

        raw_output = self._call_llm(system_prompt, user_prompt)
        if not raw_output:
            return

        # Parse output
        parsed = self.parse_llm_output(raw_output)
        if not parsed:
            return

        # Update EntityStore
        entity_store = EntityStore(output_path.parent)
        self._update_store(entity_store, parsed)

        # Save is called by EntityStore internally
        entity_store.save()

    def _update_store(self, store: EntityStore, outputs: list[KGOutput]) -> None:
        """将解析结果更新到 EntityStore"""
        from .entity_store import Entity, Relation

        # First pass: create entities
        label_to_id = {}
        for output in outputs:
            if output.is_entity and output.label:
                entity, created = store.get_or_create_entity(
                    label=output.label,
                    entity_type=output.entity_type or "object",
                    topics=output.topics_list,
                )
                label_to_id[output.label] = entity.id

        # Second pass: create relations
        for output in outputs:
            if output.is_relation and output.from_label and output.to_label:
                from_id = label_to_id.get(output.from_label)
                to_id = label_to_id.get(output.to_label)
                if from_id and to_id:
                    existing = store.query_relations(
                        rel_type=output.relation_type,
                        from_id=from_id,
                        to_id=to_id,
                    )
                    if not existing:
                        relation = Relation.create(
                            from_id=from_id,
                            to_id=to_id,
                            rel_type=output.relation_type or "related_to",
                            topics=output.topics_list,
                        )
                        store.add_relation(relation)
