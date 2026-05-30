"""Wiki sync - automatically sync conversation to wiki memory."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import BaseProvider

_WIKI_SYNC_SYSTEM_PROMPT = """You are a wiki memory curator. Given recent user conversation messages, identify 0-3 facts, preferences, or expressions worth saving to long-term wiki memory.

Output ONE JSON line per WikiPatch. Each line must be valid JSON (no markdown code blocks, no explanations).

WikiPatch fields:
- operation: "merge_section"
- slug: lowercase with hyphens, e.g. "user/ai-interest", "expression/budget-friendly", "topic/education"
- title: Short human-readable title
- type: one of [user_profile, user_preference, user_goal, communication_style, ielts_topic, language_weakness, expression_bank, timeline_month]
- mode: "ielts" or "freechat" or "global"
- section: "Summary" for facts, "Expressions" for vocab, "Weaknesses" for grammar issues, "Log" for timeline
- content: One concise sentence describing the fact
- tags: list of strings (e.g. ["vocabulary", "education"])
- topics: list of strings (e.g. ["study", "technology"])
- links: []
- sources: [{"kind": "session", "session_id": "SESSION_ID"}]
- confidence: "low" | "medium" | "high"

If nothing worth saving, output exactly: (none)

Example line:
{"operation":"merge_section","slug":"user/ai-interest","title":"User Studies AI","type":"user_profile","mode":"ielts","section":"Summary","content":"User is studying AI, basically computer science.","tags":["education","ai"],"topics":["study"],"links":[],"sources":[{"kind":"session","session_id":"abc123"}],"confidence":"high"}"""


async def sync_session_to_wiki(
    session_key: str,
    session_dir: str,
    workspace: Path,
    provider,
    model: str,
) -> int:
    """Sync latest user messages from session to wiki.

    Returns number of patches applied.
    """
    thread_path = workspace / "data" / "thread.jsonl"
    responses_path = workspace / "persona" / "user_responses.jsonl"
    session_uuid = session_key

    # Prefer the global event stream so wiki has assistant context too.
    conversation: list[tuple[str, str]] = []
    if thread_path.exists():
        try:
            with open(thread_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                source = event.get("source") if isinstance(event, dict) else {}
                if not isinstance(source, dict) or source.get("session_uuid") != session_uuid:
                    continue
                role = event.get("role")
                if role not in {"user", "assistant"}:
                    continue
                content = event.get("content")
                if isinstance(content, dict):
                    content = content.get("text", "")
                if isinstance(content, str) and content.strip():
                    conversation.append((str(role), content.strip()))
                if len(conversation) >= 10:
                    break
        except Exception as e:
            logger.warning("Wiki sync: failed to read global thread log: {}", e)

    # Fallback to user_responses for older data or if the global stream is absent.
    if not conversation and responses_path.exists():
        user_messages: list[tuple[str, str]] = []
        try:
            with open(responses_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("session_uuid") != session_uuid:
                    continue
                content = msg.get("content", "")
                if isinstance(content, dict):
                    content = content.get("text", "")
                if isinstance(content, str) and len(content.strip()) > 3:
                    user_messages.append(("user", content.strip()))
                if len(user_messages) >= 5:
                    break
        except Exception as e:
            logger.warning("Wiki sync: failed to read user_responses: {}", e)
            return 0
        conversation = user_messages

    if not conversation:
        return 0

    conversation_lines = []
    for role, content in reversed(conversation):
        label = "Assistant" if role == "assistant" else "User"
        conversation_lines.append(f"{label}: {content}")
    messages_text = "\n".join(conversation_lines)

    user_prompt = f"""Recent conversation messages from this session:
{messages_text}

Session ID: {session_uuid}

Generate 0-3 WikiPatch JSONL lines. Output only JSONL, no markdown, no explanation:"""

    try:
        response = await provider.chat(
            messages=[
                {"role": "system", "content": _WIKI_SYNC_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            max_tokens=2048,
            temperature=0.3,
        )
        raw = response.content or ""
    except Exception as e:
        logger.warning("Wiki sync: LLM call failed: {}", e)
        return 0

    # Ensure repo root is importable
    repo_root = str(workspace)
    if not (Path(repo_root) / "subagent").exists():
        repo_root = str(Path(__file__).resolve().parent.parent.parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        from subagent.cross_session.wiki.processor.wiki_processor import WikiProcessor

        wiki_root = workspace / "persona" / "wiki"
        processor = WikiProcessor(wiki_root=wiki_root)
        patches = processor.process_jsonl(raw)

        if patches:
            logger.info(
                "Wiki sync: applied {} patch(es) for session {}",
                len(patches),
                session_uuid,
            )
        return len(patches)
    except Exception as e:
        logger.warning("Wiki sync: failed to apply patches: {}", e)
        return 0
