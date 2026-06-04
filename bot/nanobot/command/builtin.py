"""Built-in slash command handlers."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import suppress
from dataclasses import dataclass

from nanobot import __version__
from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.utils.helpers import build_status_content
from nanobot.utils.restart import set_restart_notice_to_env


@dataclass(frozen=True)
class BuiltinCommandSpec:
    command: str
    title: str
    description: str
    icon: str
    arg_hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "command": self.command,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "arg_hint": self.arg_hint,
        }


BUILTIN_COMMAND_SPECS: tuple[BuiltinCommandSpec, ...] = (
    BuiltinCommandSpec(
        "/new",
        "New chat",
        "Stop the current task and start a fresh conversation.",
        "square-pen",
    ),
    BuiltinCommandSpec(
        "/freechat",
        "Free chat",
        "Start a new conversation with a random IELTS topic.",
        "sparkles",
    ),
    BuiltinCommandSpec(
        "/ielts",
        "IELTS Mode",
        "Switch to IELTS speaking practice mode.",
        "graduation-cap",
    ),
    BuiltinCommandSpec(
        "/ielts_exam",
        "IELTS Exam",
        "Start an IELTS speaking exam (full test simulation).",
        "clipboard-list",
    ),
    BuiltinCommandSpec(
        "/ielts_score",
        "IELTS Score",
        "Get AI evaluation and band scores for your IELTS speaking practice.",
        "star",
    ),
    BuiltinCommandSpec(
        "/benative",
        "Be Native",
        "Practice Chinese-to-English reconstruction with article sentence pairs.",
        "languages",
    ),
    BuiltinCommandSpec(
        "/stop",
        "Stop current task",
        "Cancel the active agent turn for this chat.",
        "square",
    ),
    BuiltinCommandSpec(
        "/restart",
        "Restart nanobot",
        "Restart the bot process in place.",
        "rotate-cw",
    ),
    BuiltinCommandSpec(
        "/status",
        "Show status",
        "Display runtime, provider, and channel status.",
        "activity",
    ),
    BuiltinCommandSpec(
        "/model",
        "Switch model preset",
        "Show or switch the active model preset.",
        "brain",
        "[preset]",
    ),
    BuiltinCommandSpec(
        "/history",
        "Show conversation history",
        "Print the last N persisted conversation messages.",
        "history",
        "[n]",
    ),
    BuiltinCommandSpec(
        "/goal",
        "Start long-running goal",
        "Tell the agent to treat the request as a long-running goal.",
        "activity",
        "<goal>",
    ),
    BuiltinCommandSpec(
        "/dream",
        "Run Dream",
        "Manually trigger memory consolidation.",
        "sparkles",
    ),
    BuiltinCommandSpec(
        "/dream-log",
        "Show Dream log",
        "Show what the last Dream consolidation changed.",
        "book-open",
    ),
    BuiltinCommandSpec(
        "/dream-restore",
        "Restore memory",
        "Revert memory to a previous Dream snapshot.",
        "undo-2",
    ),
    BuiltinCommandSpec(
        "/help",
        "Show help",
        "List available slash commands.",
        "circle-help",
    ),
    BuiltinCommandSpec(
        "/pairing",
        "Manage pairing",
        "List, approve, deny or revoke pairing requests.",
        "shield",
        "[list|approve <code>|deny <code>|revoke <user_id>]",
    ),
)


def builtin_command_palette() -> list[dict[str, str]]:
    """Return structured command metadata for UI command palettes."""
    return [spec.as_dict() for spec in BUILTIN_COMMAND_SPECS]


async def cmd_stop(ctx: CommandContext) -> OutboundMessage:
    """Cancel all active tasks and subagents for the session."""
    loop = ctx.loop
    msg = ctx.msg
    total = await loop._cancel_active_tasks(msg.session_key)
    content = f"Stopped {total} task(s)." if total else "No active task to stop."
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content=content,
        metadata=dict(msg.metadata or {})
    )


async def cmd_restart(ctx: CommandContext) -> OutboundMessage:
    """Restart the process in-place via os.execv."""
    msg = ctx.msg
    set_restart_notice_to_env(
        channel=msg.channel,
        chat_id=msg.chat_id,
        metadata=dict(msg.metadata or {}),
    )

    async def _do_restart():
        await asyncio.sleep(1)
        os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

    asyncio.create_task(_do_restart())
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content="Restarting...",
        metadata=dict(msg.metadata or {})
    )


async def cmd_status(ctx: CommandContext) -> OutboundMessage:
    """Build an outbound status message for a session."""
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    ctx_est = 0
    with suppress(Exception):
        ctx_est, _ = loop.consolidator.estimate_session_prompt_tokens(session)
    if ctx_est <= 0:
        ctx_est = loop._last_usage.get("prompt_tokens", 0)

    # Fetch web search provider usage (best-effort, never blocks the response)
    search_usage_text: str | None = None
    # Never let usage fetch break /status
    with suppress(Exception):
        from nanobot.utils.searchusage import fetch_search_usage
        web_cfg = getattr(loop, "web_config", None)
        search_cfg = getattr(web_cfg, "search", None) if web_cfg else None
        if search_cfg is not None:
            provider = getattr(search_cfg, "provider", "duckduckgo")
            api_key = getattr(search_cfg, "api_key", "") or None
            usage = await fetch_search_usage(provider=provider, api_key=api_key)
            search_usage_text = usage.format()
    active_tasks = loop._active_tasks.get(ctx.key, [])
    task_count = sum(1 for t in active_tasks if not t.done())
    with suppress(Exception):
        task_count += loop.subagents.get_running_count_by_session(ctx.key)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_status_content(
            version=__version__, model=loop.model,
            start_time=loop._start_time, last_usage=loop._last_usage,
            context_window_tokens=loop.context_window_tokens,
            session_msg_count=len(session.get_history(max_messages=0)),
            context_tokens_estimate=ctx_est,
            search_usage_text=search_usage_text,
            active_task_count=task_count,
            max_completion_tokens=getattr(
                getattr(loop.provider, "generation", None), "max_tokens", 8192
            ),
        ),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


async def cmd_new(ctx: CommandContext) -> OutboundMessage:
    """Stop active task and start a fresh session."""
    loop = ctx.loop
    await loop._cancel_active_tasks(ctx.key)
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    snapshot = session.messages[session.last_consolidated:]
    session.clear()
    loop.sessions.save(session)
    loop.sessions.invalidate(session.key)
    if snapshot:
        loop._schedule_background(loop.consolidator.archive(snapshot))
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content="New session started.",
        metadata=dict(ctx.msg.metadata or {})
    )


async def cmd_freechat(ctx: CommandContext) -> OutboundMessage | None:
    """Select a topic that hasn't been fully explored and start a conversation.

    Sets session mode to "freechat" and updates counter_engine to use mode-specific triggers.
    """
    import random
    import re

    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)

    # Set mode to freechat
    session.metadata["mode"] = "freechat"
    loop.counter_engine.set_mode("freechat")
    loop.sessions.save(session)

    # Get mode-specific topic_bank path (check context/ subdir first)
    mode = session.metadata.get("mode", "freechat")
    topic_bank_path = loop.workspace / "mode" / mode / "context" / "topic_bank.md"

    if not topic_bank_path.exists():
        # Fall back to mode root
        topic_bank_path = loop.workspace / "mode" / mode / "topic_bank.md"

    if not topic_bank_path.exists():
        # Fall back to workspace root
        topic_bank_path = loop.workspace / "topic_bank.md"

    if not topic_bank_path.exists():
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="Topic bank not found. Please ensure topic_bank.md exists in the workspace.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    try:
        topic_content = topic_bank_path.read_text(encoding="utf-8")
    except Exception as e:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=f"Failed to read topic bank: {e}",
            metadata=dict(ctx.msg.metadata or {}),
        )

    # Parse the new topic bank format with depth levels
    # Structure: Topic: X | Question | Depth | Sub-topic
    questions_by_topic = {}  # topic_name -> [(question, depth, sub_topic), ...]
    current_topic = None
    current_section = ""

    for line in topic_content.split("\n"):
        # Track section headers (###)
        if line.startswith("### "):
            current_section = line.replace("### ", "").strip()
        # Track topic headers (#### Topic:)
        elif line.startswith("#### Topic:"):
            current_topic = line.replace("#### Topic:", "").strip()
        # Parse question rows: | Question | Depth | Sub-topic |
        elif line.startswith("|") and "|" in line[1:] and not line.startswith("|----"):
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]  # Remove empty strings
            if len(parts) >= 3:
                question = parts[0]
                try:
                    depth = int(parts[1])
                except ValueError:
                    continue
                sub_topic = parts[2] if len(parts) > 2 else ""

                if question and "?" in question and current_topic:
                    if current_topic not in questions_by_topic:
                        questions_by_topic[current_topic] = []
                    questions_by_topic[current_topic].append({
                        "question": question,
                        "depth": depth,
                        "sub_topic": sub_topic,
                    })

    if not questions_by_topic:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="No topics found in topic bank. Please add topics in the correct format.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    # Try to read profile to check exploration status
    profile_data = {}
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    session_dir = loop.sessions._get_session_dir(session.key)
    profile_path = session_dir / "notes" / "profile.md"

    if profile_path.exists():
        try:
            profile_content = profile_path.read_text(encoding="utf-8")
            # Parse exploration status from profile
            # Look for lines like: | Favorite Sport | in_progress | 3 |
            for line in profile_content.split("\n"):
                if line.startswith("|") and "not_explored" in line or "in_progress" in line or "completed" in line:
                    parts = [p.strip() for p in line.split("|")]
                    parts = [p for p in parts if p]
                    if len(parts) >= 4 and parts[0] not in ("Topic", "topic"):
                        topic_name = parts[0]
                        status = parts[1]
                        try:
                            max_depth = int(parts[2])
                        except ValueError:
                            max_depth = 0
                        profile_data[topic_name] = {"status": status, "max_depth": max_depth}
        except Exception:
            pass

    # Select a topic based on exploration status
    # Priority: not_explored > in_progress with depth < 3
    not_explored_topics = [t for t, data in profile_data.items()
                          if data["status"] == "not_explored" or data["status"] == ""]
    in_progress_topics = [t for t, data in profile_data.items()
                         if data["status"] == "in_progress" and data["max_depth"] < 4]

    candidates = not_explored_topics
    if not candidates:
        candidates = in_progress_topics

    if not candidates:
        # No prior data or all completed - pick random topic
        candidates = list(questions_by_topic.keys())

    if not candidates:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="No available topics found.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    # Pick a random topic from candidates
    selected_topic = random.choice(candidates)
    questions = questions_by_topic[selected_topic]

    # Get prior depth for this topic
    prior_depth = 0
    if selected_topic in profile_data:
        prior_depth = profile_data[selected_topic].get("max_depth", 0)

    # For new topics (prior_depth=0), always start with the first depth 1 question
    # which is typically the simplest "do you X?" preference question
    # For continuing topics, move to the next depth level
    if prior_depth == 0:
        # New topic - use the first (simplest) depth 1 question
        depth_1_questions = [q for q in questions if q["depth"] == 1]
        if depth_1_questions:
            # Use the first one which is typically the simplest
            question_data = depth_1_questions[0]
        else:
            question_data = random.choice(questions)
    else:
        # Continuing topic - find next depth level
        next_depth = min(prior_depth + 1, 5)
        suitable_questions = [q for q in questions if q["depth"] == next_depth]

        # If no questions at exact depth, try nearby depths
        if not suitable_questions:
            for d in range(next_depth - 1, 0, -1):
                suitable_questions = [q for q in questions if q["depth"] == d]
                if suitable_questions:
                    break

        if not suitable_questions:
            suitable_questions = [q for q in questions if q["depth"] == 1]

        question_data = random.choice(suitable_questions)
    question = question_data["question"]
    topic = selected_topic

    # Set session title to topic name (folder stays as UUID)
    session.metadata["title"] = topic
    loop.sessions.save(session)

    # Use PromptInjector to render the freechat template
    from nanobot.prompt_injector import PromptInjector
    injector = PromptInjector(loop.workspace)
    intro_prompt = injector.inject("freechat", {
        "topic": topic,
        "question": question,
    })

    ctx.msg.content = intro_prompt
    return None


async def cmd_ielts(ctx: CommandContext) -> OutboundMessage | None:
    """Switch to IELTS speaking practice mode.

    Sets session mode to "ielts" and updates counter_engine to use mode-specific triggers.
    """
    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)

    # Set mode to ielts
    session.metadata["mode"] = "ielts"
    loop.counter_engine.set_mode("ielts")
    loop.sessions.save(session)

    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="Switched to IELTS speaking practice mode. Your responses will be analyzed for vocabulary, grammar, and fluency.",
        metadata=dict(ctx.msg.metadata or {}),
    )


async def cmd_ielts_exam(ctx: CommandContext) -> OutboundMessage | None:
    """Start an IELTS speaking exam simulation.

    Usage:
    - /ielts_exam - Shows topic list for selection
    - /ielts_exam random - Starts exam with random topic
    - /ielts_exam <topic_number> - Starts exam with specific topic (e.g., /ielts_exam 01)

    The exam follows the standard IELTS speaking format:
    - Part 1: Introduction & Interview (3-4 questions)
    - Part 2: Long Turn (cue card + 1-2 minute speech)
    - Part 3: Discussion (4-5 questions)
    """
    from pathlib import Path

    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)
    workspace = loop.workspace

    args = ctx.args.strip() if ctx.args else ""

    # Get topic bank path
    topic_bank_path = workspace / "topic-bank"

    # List available topics
    topics = []
    for topic_file in sorted(topic_bank_path.glob("*.md")):
        topic_name = topic_file.stem  # e.g., "01_animals"
        topic_title = topic_file.read_text(encoding="utf-8").split("\n")[0].replace("# ", "").strip()
        topics.append({
            "id": topic_file.stem,
            "title": topic_title,
            "file": str(topic_file),
        })

    if not topics:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="No topics found in topic-bank directory.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    # Initialize exam manager
    from nanobot.ielts_exam import IeltsExamManager
    exam_manager = IeltsExamManager(workspace)

    if args == "random":
        # Random topic - start exam immediately
        import random
        selected = random.choice(topics)
        topic_file = Path(selected["file"])
        topic_content = topic_file.read_text(encoding="utf-8")
        exam = exam_manager.load_topic(topic_file)

        # Store exam manager in session metadata for later use
        session.metadata["ielts_exam_id"] = exam.exam_id
        session.metadata["ielts_exam_state"] = exam.state.value
        loop.sessions.save(session)

        # Use PromptInjector to render the ielts_exam template
        from nanobot.prompt_injector import PromptInjector
        injector = PromptInjector(loop.workspace)
        intro_prompt = injector.inject("ielts_exam", {
            "topic_title": selected["title"],
            "topic_content": topic_content,
        })

        metadata = dict(ctx.msg.metadata or {})
        metadata["ielts_exam"] = {
            "exam_id": exam.exam_id,
            "topic": selected["title"],
            "state": exam.state.value,
            "current_part": exam.current_part.value,
        }

        ctx.msg.content = intro_prompt
        ctx.msg.metadata = metadata
        return None

    elif args:
        # Specific topic - find by slug (e.g., "animals", "art") or full id (e.g., "01_animals")
        selected = None
        for topic in topics:
            topic_slug = topic["id"].split("_", 1)[-1]  # "01_animals" -> "animals"
            if topic_slug == args.lower() or topic["id"] == args:
                selected = topic
                break

        if not selected:
            # Show topic list with error message
            content = f"## Topic not found: {args}\n\n"
            content += "**Usage:** `/ielts_exam <topic>` or `/ielts_exam random`\n\n"
            content += "### Available Topics:\n\n"
            for topic in topics:
                topic_slug = topic["id"].split("_", 1)[-1]
                content += f"- **{topic_slug}**: {topic['title']}\n"
            content += "\n*Or type `/ielts_exam random` for a random topic.*"
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=content,
                metadata=dict(ctx.msg.metadata or {}),
            )

        topic_file = Path(selected["file"])
        topic_content = topic_file.read_text(encoding="utf-8")
        exam = exam_manager.load_topic(topic_file)

        # Store exam manager in session metadata for later use
        session.metadata["ielts_exam_id"] = exam.exam_id
        session.metadata["ielts_exam_state"] = exam.state.value
        loop.sessions.save(session)

        # Use PromptInjector to render the ielts_exam template
        from nanobot.prompt_injector import PromptInjector
        injector = PromptInjector(loop.workspace)
        intro_prompt = injector.inject("ielts_exam", {
            "topic_title": selected["title"],
            "topic_content": topic_content,
        })

        metadata = dict(ctx.msg.metadata or {})
        metadata["ielts_exam"] = {
            "exam_id": exam.exam_id,
            "topic": selected["title"],
            "state": exam.state.value,
            "current_part": exam.current_part.value,
        }

        ctx.msg.content = intro_prompt
        ctx.msg.metadata = metadata
        return None

    else:
        # Show topic list for selection
        content = "## IELTS Speaking Exam - Select a Topic\n\n"
        content += "**Usage:** `/ielts_exam <topic>` or `/ielts_exam random`\n\n"
        content += "### Available Topics:\n\n"

        for topic in topics:
            topic_slug = topic["id"].split("_", 1)[-1]
            content += f"- **{topic_slug}**: {topic['title']}\n"

        content += "\n*Or type `/ielts_exam random` for a random topic.*"

        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=content,
            metadata=dict(ctx.msg.metadata or {}),
        )


async def cmd_ielts_score(ctx: CommandContext) -> OutboundMessage | None:
    """Get AI evaluation and band scores for IELTS speaking practice.

    Reads the conversation history from the current session and spawns
    an evaluator subagent to provide detailed feedback and band scores.
    """

    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)

    # Read conversation history from thread.jsonl
    try:
        thread_path = loop.sessions._get_session_path(session.key)
        if not thread_path.exists():
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="No conversation history found for this session.",
                metadata=dict(ctx.msg.metadata or {}),
            )

        # Read and parse thread.jsonl
        lines = thread_path.read_text(encoding="utf-8").strip().split("\n")
        messages = []
        for line in lines:
            try:
                msg = json.loads(line)
                if msg.get("role") and msg.get("content"):
                    messages.append(f"**{msg['role'].capitalize()}:** {msg['content']}")
            except json.JSONDecodeError:
                continue

        if not messages:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="No messages found in conversation history.",
                metadata=dict(ctx.msg.metadata or {}),
            )

        conversation = "\n\n".join(messages)

    except Exception as e:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"Failed to read conversation history: {e}",
            metadata=dict(ctx.msg.metadata or {}),
        )

    # Load the evaluator prompt template
    evaluator_prompt_path = loop.workspace / "subagent" / "cross_session" / "ielts_exam" / "context" / "ielts_score_subagent.md"
    if not evaluator_prompt_path.exists():
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Evaluator prompt not found. Please ensure ielts_score_subagent.md exists.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    evaluator_prompt = evaluator_prompt_path.read_text(encoding="utf-8")

    # Inject conversation into the prompt
    task_prompt = evaluator_prompt.replace("{{conversation}}", conversation)

    # Spawn the evaluator subagent (model resolved automatically from subagent_defaults by label)
    try:
        task_id = await loop.subagents.spawn(
            task=task_prompt,
            label="IELTS Score",
            origin_channel=ctx.msg.channel,
            origin_chat_id=ctx.msg.chat_id,
            session_key=ctx.key,
            announce_result=True,
        )

        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"🤖 IELTS evaluator started... Analyzing your speaking performance. This may take a moment.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    except Exception as e:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"Failed to start evaluator: {e}",
            metadata=dict(ctx.msg.metadata or {}),
        )


async def cmd_benative(ctx: CommandContext) -> OutboundMessage | None:
    """Switch to Be Native mode for authentic expression practice.

    Sets session mode to "benative" and shows available articles for practice.
    Usage: /benative [select <article_id>]
    """
    from datetime import datetime

    loop = ctx.loop
    session = ctx.session or loop.sessions.get_or_create(ctx.key)

    args = ctx.args.strip() if ctx.args else ""

    # Handle /benative select <article_id>
    if args.startswith("select "):
        article_id = args[7:].strip()
        if not article_id:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="Please provide an article ID. Usage: `/benative select <article_id>`",
                metadata=dict(ctx.msg.metadata or {}),
            )

        # Set mode and store article selection
        session.metadata["mode"] = "benative"
        session.metadata["benative_article_id"] = article_id
        loop.counter_engine.set_mode("benative")
        loop.sessions.save(session)

        # Save progress file
        session_dir = loop.sessions._get_session_dir(session.key)
        notes_dir = session_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        progress_file = notes_dir / "benative_progress.json"

        # Count total sentences
        benative_root = loop.sessions.sessions_dir.parent / "benative"
        pairs_file = benative_root / "pairs" / f"{article_id}.jsonl"
        total_sentences = 0
        if pairs_file.exists():
            total_sentences = sum(1 for _ in pairs_file.read_text(encoding="utf-8").strip().split("\n") if _.strip())

        progress_data = {
            "article_id": article_id,
            "current_sentence": 0,
            "total_sentences": total_sentences,
            "selected_at": datetime.now().isoformat(),
        }
        progress_file.write_text(json.dumps(progress_data, ensure_ascii=False), encoding="utf-8")

        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"""Article selected! You're now in Benative practice mode.

Current progress: 0/{total_sentences} sentences

I'll show you Chinese sentences one by one. Try to translate them into natural English!

Type `/benative progress` to see your current progress.""",
            metadata=dict(ctx.msg.metadata or {}),
        )

    # Handle /benative progress
    if args == "progress":
        session_dir = loop.sessions._get_session_dir(session.key)
        progress_file = session_dir / "notes" / "benative_progress.json"
        if progress_file.exists():
            progress_data = json.loads(progress_file.read_text(encoding="utf-8"))
            article_id = progress_data.get("article_id", "unknown")
            current = progress_data.get("current_sentence", 0)
            total = progress_data.get("total_sentences", 0)
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content=f"Current progress: {current}/{total} sentences\nArticle ID: {article_id}",
                metadata=dict(ctx.msg.metadata or {}),
            )
        else:
            return OutboundMessage(
                channel=ctx.msg.channel,
                chat_id=ctx.msg.chat_id,
                content="No active benative practice. Use `/benative` to start.",
                metadata=dict(ctx.msg.metadata or {}),
            )

    # Default: /benative - show article list
    session.metadata["mode"] = "benative"
    loop.counter_engine.set_mode("benative")
    loop.sessions.save(session)

    # List available articles
    benative_root = loop.sessions.sessions_dir.parent / "benative"
    articles_dir = benative_root / "articles"
    article_list = []

    if articles_dir.exists():
        for article_file in articles_dir.glob("*.json"):
            try:
                article_data = json.loads(article_file.read_text(encoding="utf-8"))
                # Count sentences from corresponding pairs file
                pairs_file = articles_dir.parent / "pairs" / f"{article_file.stem}.jsonl"
                sentence_count = 0
                if pairs_file.exists():
                    sentence_count = sum(1 for _ in pairs_file.read_text(encoding="utf-8").strip().split("\n") if _.strip())
                article_list.append({
                    "id": article_data.get("id", article_file.stem),
                    "title": article_data.get("title", "Untitled"),
                    "source": article_data.get("source", "Unknown"),
                    "topic": article_data.get("topic", "general"),
                    "sentence_count": sentence_count,
                })
            except Exception:
                continue

    if not article_list:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="""Switched to Be Native mode for authentic expression practice.

No articles available yet. Articles are fetched daily at 12:00. Please check back later or wait for the next fetch cycle.""",
            metadata=dict(ctx.msg.metadata or {}),
        )

    # Format article list
    lines = ["**Available Articles for Practice:**\n"]
    for i, article in enumerate(article_list, 1):
        lines.append(f"{i}. **{article['title']}** ({article['source']}) - {article['topic']} - {article['sentence_count']} sentences")

    lines.append("\nTo select an article, reply with the number (e.g., `1`) or the article ID.")
    lines.append("\nOnce selected, I'll show you Chinese sentences one by one. Try to translate them into natural English!")

    content = "\n".join(lines)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=content,
        metadata=dict(ctx.msg.metadata or {}),
    )


def _format_preset_names(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names) if names else "(none configured)"


def _model_preset_names(loop) -> list[str]:
    names = set(loop.model_presets)
    names.add("default")
    return ["default", *sorted(name for name in names if name != "default")]


def _active_model_preset_name(loop) -> str:
    return loop.model_preset or "default"


def _command_error_message(exc: Exception) -> str:
    return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)


def _model_command_status(loop) -> str:
    names = _model_preset_names(loop)
    active = _active_model_preset_name(loop)
    return "\n".join([
        "## Model",
        f"- Current model: `{loop.model}`",
        f"- Current preset: `{active}`",
        f"- Available presets: {_format_preset_names(names)}",
    ])


async def cmd_model(ctx: CommandContext) -> OutboundMessage:
    """Show or switch model presets."""
    loop = ctx.loop
    args = ctx.args.strip()
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}

    if not args:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=_model_command_status(loop),
            metadata=metadata,
        )

    parts = args.split()
    if len(parts) != 1:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: `/model [preset]`",
            metadata=metadata,
        )

    name = parts[0]
    try:
        loop.set_model_preset(name)
    except (KeyError, ValueError) as exc:
        names = _model_preset_names(loop)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                f"Could not switch model preset: {_command_error_message(exc)}\n\n"
                f"Available presets: {_format_preset_names(names)}"
            ),
            metadata=metadata,
        )

    max_tokens = getattr(getattr(loop.provider, "generation", None), "max_tokens", None)
    lines = [
        f"Switched model preset to `{loop.model_preset}`.",
        f"- Model: `{loop.model}`",
        f"- Context window: {loop.context_window_tokens}",
    ]
    if max_tokens is not None:
        lines.append(f"- Max output tokens: {max_tokens}")
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content="\n".join(lines),
        metadata=metadata,
    )


async def cmd_dream(ctx: CommandContext) -> OutboundMessage:
    """Manually trigger a Dream consolidation run."""
    import time

    loop = ctx.loop
    msg = ctx.msg

    async def _run_dream():
        t0 = time.monotonic()
        try:
            did_work = await loop.dream.run()
            elapsed = time.monotonic() - t0
            if did_work:
                content = f"Dream completed in {elapsed:.1f}s."
            else:
                content = "Dream: nothing to process."
        except Exception as e:
            elapsed = time.monotonic() - t0
            content = f"Dream failed after {elapsed:.1f}s: {e}"
        await loop.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    asyncio.create_task(_run_dream())
    return OutboundMessage(
        channel=msg.channel, chat_id=msg.chat_id, content="Dreaming...",
    )


def _extract_changed_files(diff: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files: list[str] = []
    seen: set[str] = set()
    for line in diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        path = parts[3]
        if path.startswith("b/"):
            path = path[2:]
        if path in seen:
            continue
        seen.add(path)
        files.append(path)
    return files


def _format_changed_files(diff: str) -> str:
    files = _extract_changed_files(diff)
    if not files:
        return "No tracked memory files changed."
    return ", ".join(f"`{path}`" for path in files)


def _format_dream_log_content(commit, diff: str, *, requested_sha: str | None = None) -> str:
    files_line = _format_changed_files(diff)
    lines = [
        "## Dream Update",
        "",
        "Here is the selected Dream memory change." if requested_sha else "Here is the latest Dream memory change.",
        "",
        f"- Commit: `{commit.sha}`",
        f"- Time: {commit.timestamp}",
        f"- Changed files: {files_line}",
    ]
    if diff:
        lines.extend([
            "",
            f"Use `/dream-restore {commit.sha}` to undo this change.",
            "",
            "```diff",
            diff.rstrip(),
            "```",
        ])
    else:
        lines.extend([
            "",
            "Dream recorded this version, but there is no file diff to display.",
        ])
    return "\n".join(lines)


def _format_dream_restore_list(commits: list) -> str:
    lines = [
        "## Dream Restore",
        "",
        "Choose a Dream memory version to restore. Latest first:",
        "",
    ]
    for c in commits:
        lines.append(f"- `{c.sha}` {c.timestamp} - {c.message.splitlines()[0]}")
    lines.extend([
        "",
        "Preview a version with `/dream-log <sha>` before restoring it.",
        "Restore a version with `/dream-restore <sha>`.",
    ])
    return "\n".join(lines)


async def cmd_dream_log(ctx: CommandContext) -> OutboundMessage:
    """Show what the last Dream changed.

    Default: diff of the latest commit (HEAD~1 vs HEAD).
    With /dream-log <sha>: diff of that specific commit.
    """
    store = ctx.loop.consolidator.store
    git = store.git

    if not git.is_initialized():
        if store.get_last_dream_cursor() == 0:
            msg = "Dream has not run yet. Run `/dream`, or wait for the next scheduled Dream cycle."
        else:
            msg = "Dream history is not available because memory versioning is not initialized."
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content=msg, metadata={"render_as": "text"},
        )

    args = ctx.args.strip()

    if args:
        # Show diff of a specific commit
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        if not result:
            content = (
                f"Couldn't find Dream change `{sha}`.\n\n"
                "Use `/dream-restore` to list recent versions, "
                "or `/dream-log` to inspect the latest one."
            )
        else:
            commit, diff = result
            content = _format_dream_log_content(commit, diff, requested_sha=sha)
    else:
        # Default: show the latest commit's diff
        commits = git.log(max_entries=1)
        result = git.show_commit_diff(commits[0].sha) if commits else None
        if result:
            commit, diff = result
            content = _format_dream_log_content(commit, diff)
        else:
            content = "Dream memory has no saved versions yet."

    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


async def cmd_dream_restore(ctx: CommandContext) -> OutboundMessage:
    """Restore memory files from a previous dream commit.

    Usage:
        /dream-restore          — list recent commits
        /dream-restore <sha>    — revert a specific commit
    """
    store = ctx.loop.consolidator.store
    git = store.git
    if not git.is_initialized():
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="Dream history is not available because memory versioning is not initialized.",
        )

    args = ctx.args.strip()
    if not args:
        # Show recent commits for the user to pick
        commits = git.log(max_entries=10)
        if not commits:
            content = "Dream memory has no saved versions to restore yet."
        else:
            content = _format_dream_restore_list(commits)
    else:
        sha = args.split()[0]
        result = git.show_commit_diff(sha)
        changed_files = _format_changed_files(result[1]) if result else "the tracked memory files"
        new_sha = git.revert(sha)
        if new_sha:
            content = (
                f"Restored Dream memory to the state before `{sha}`.\n\n"
                f"- New safety commit: `{new_sha}`\n"
                f"- Restored files: {changed_files}\n\n"
                f"Use `/dream-log {new_sha}` to inspect the restore diff."
            )
        else:
            content = (
                f"Couldn't restore Dream change `{sha}`.\n\n"
                "It may not exist, or it may be the first saved version with no earlier state to restore."
            )
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=content, metadata={"render_as": "text"},
    )


_HISTORY_DEFAULT_COUNT = 10
_HISTORY_MAX_COUNT = 50
_HISTORY_MAX_CONTENT_CHARS = 200


def _format_history_message(msg: dict) -> str | None:
    """Format a single history message for display. Returns None to skip."""
    role = msg.get("role")
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content") or ""
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        content = " ".join(parts)
    content = str(content).strip()
    if not content:
        return None
    if len(content) > _HISTORY_MAX_CONTENT_CHARS:
        content = content[:_HISTORY_MAX_CONTENT_CHARS] + "…"
    label = "👤 You" if role == "user" else "🤖 Bot"
    return f"{label}: {content}"


async def cmd_history(ctx: CommandContext) -> OutboundMessage:
    """Show the last N messages of the current session (default 10, max 50).

    Usage: /history [count]
    """
    count = _HISTORY_DEFAULT_COUNT
    if ctx.args.strip():
        try:
            count = max(1, min(int(ctx.args.strip()), _HISTORY_MAX_COUNT))
        except ValueError:
            return OutboundMessage(
                channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
                content="Usage: /history [count] — e.g. /history 5 (default: 10, max: 50)",
                metadata=dict(ctx.msg.metadata or {}),
            )

    session = ctx.session or ctx.loop.sessions.get_or_create(ctx.key)
    history = session.get_history(max_messages=0)
    visible = [_format_history_message(m) for m in history]
    visible = [m for m in visible if m is not None]
    recent = visible[-count:]

    if not recent:
        return OutboundMessage(
            channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
            content="No conversation history yet.",
            metadata=dict(ctx.msg.metadata or {}),
        )

    header = f"Last {len(recent)} message(s):\n"
    return OutboundMessage(
        channel=ctx.msg.channel, chat_id=ctx.msg.chat_id,
        content=header + "\n".join(recent),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


_GOAL_PROMPT_TEMPLATE = """The user declared a sustained objective for this thread.

Inspect or clarify if needed, then call `long_task` with the refined objective (and optional short ui_summary). Work proceeds as normal assistant turns using your usual tools. When the objective is fully done and verified, call `complete_goal` with a brief recap. If the user later cancels or changes direction, still call `complete_goal` with an honest recap (then `long_task` again only after there is no active goal). Do not use `long_task` / `complete_goal` for trivial one-shot answers.

Goal:
{goal}
"""


async def cmd_goal(ctx: CommandContext) -> OutboundMessage | None:
    """Rewrite /goal into a normal agent turn that nudges long_task use."""
    goal = ctx.args.strip()
    if not goal:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content="Usage: /goal <long-running task description>",
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )
    if ctx.session is None:
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=(
                "A task is already running for this chat. "
                "Use `/stop` first, then send `/goal <long-running task description>` again."
            ),
            metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
        )

    ctx.msg.metadata = {
        **dict(ctx.msg.metadata or {}),
        "original_command": "/goal",
        "original_content": ctx.raw,
        "goal_started_at": time.time(),
    }
    ctx.msg.content = _GOAL_PROMPT_TEMPLATE.format(goal=goal)
    return None


async def cmd_pairing(ctx: CommandContext) -> OutboundMessage:
    """List, approve, deny or revoke pairing requests."""
    from nanobot.pairing import PAIRING_COMMAND_META_KEY, handle_pairing_command

    reply = handle_pairing_command(ctx.msg.channel, ctx.args)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=reply,
        metadata={PAIRING_COMMAND_META_KEY: True},
    )


async def cmd_help(ctx: CommandContext) -> OutboundMessage:
    """Return available slash commands."""
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=build_help_text(),
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def build_help_text() -> str:
    """Build canonical help text shared across channels."""
    lines = ["🐈 nanobot commands:"]
    for spec in BUILTIN_COMMAND_SPECS:
        command = spec.command
        if spec.arg_hint:
            command = f"{command} {spec.arg_hint}"
        lines.append(f"{command} — {spec.description}")
    return "\n".join(lines)


def register_builtin_commands(router: CommandRouter) -> None:
    """Register the default set of slash commands."""
    router.priority("/stop", cmd_stop)
    router.priority("/restart", cmd_restart)
    router.priority("/status", cmd_status)
    router.exact("/new", cmd_new)
    router.exact("/freechat", cmd_freechat)
    router.exact("/ielts", cmd_ielts)
    router.exact("/ielts_exam", cmd_ielts_exam)
    router.exact("/ielts_score", cmd_ielts_score)
    router.exact("/benative", cmd_benative)
    router.exact("/status", cmd_status)
    router.exact("/model", cmd_model)
    router.prefix("/model ", cmd_model)
    router.exact("/history", cmd_history)
    router.prefix("/history ", cmd_history)
    router.exact("/goal", cmd_goal)
    router.prefix("/goal ", cmd_goal)
    router.exact("/dream", cmd_dream)
    router.exact("/dream-log", cmd_dream_log)
    router.prefix("/dream-log ", cmd_dream_log)
    router.exact("/dream-restore", cmd_dream_restore)
    router.prefix("/dream-restore ", cmd_dream_restore)
    router.exact("/help", cmd_help)
    router.exact("/pairing", cmd_pairing)
    router.prefix("/pairing ", cmd_pairing)
