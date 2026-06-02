"""通用工具函数 for Data Processors."""

from pathlib import Path


def parse_tab_line(line: str, field_count: int, min_fields: int | None = None) -> list[str]:
    """解析 tab 分隔的字段行

    Args:
        line: LLM 输出的一行，如 "3 points\tthree-point shot\texpression\t更专业"
        field_count: 最多读取的字段数量
        min_fields: 最少需要的字段数量，默认等于 field_count

    Returns:
        字段列表；字段不足时返回空列表
    """
    parts = line.strip().split("\t")
    required = field_count if min_fields is None else min_fields
    if len(parts) < required:
        return []
    return parts[:field_count]


def split_batch_items(raw_output: str) -> list[str]:
    """按 --- 分隔批量输出

    LLM 返回格式：
    item1_field1\titem1_field2\t...
    item2_field1\titem2_field2\t...

    ---

    item3_field1\titem3_field2\t...
    """
    items = raw_output.split("\n---\n")
    return [item.strip() for item in items if item.strip()]


def parse_batch_output(
    raw_output: str,
    field_names: list[str],
    none_marker: str = "(none)",
) -> list[dict]:
    """解析批量 LLM 输出

    Args:
        raw_output: LLM 返回的原始文本
        field_names: 字段名列表，如 ["original", "improved", "type", "reason"]
        none_marker: 表示"无内容"的标记

    Returns:
        list[dict]，每个 dict 对应一个 message 的解析结果
        如果某个 message 没有改进点，返回空 list
    """
    results = []
    items = split_batch_items(raw_output)
    field_count = len(field_names)

    for item in items:
        lines = item.strip().split("\n")
        item_results = []
        for line in lines:
            line = line.strip()
            if not line or line == none_marker:
                continue
            parsed = parse_tab_line(line, field_count)
            if parsed:
                item_results.append(dict(zip(field_names, parsed)))
        results.append(item_results)
    return results


def ensure_output_dir(path: Path) -> None:
    """确保输出目录存在"""
    path.parent.mkdir(parents=True, exist_ok=True)
