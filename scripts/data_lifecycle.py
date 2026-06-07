"""Development reset and export helpers for runtime data.

The script is intentionally conservative: reset operations keep long-term user
memory unless --clear-user-memory is passed.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


def reset_dev_data(
    workspace: Path,
    *,
    clear_monitor: bool = False,
    clear_processors: bool = False,
    clear_wiki_index: bool = False,
    clear_user_memory: bool = False,
) -> dict[str, list[str]]:
    removed: list[str] = []
    kept: list[str] = []

    def remove(path: Path) -> None:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(_rel(path, workspace))

    if clear_monitor:
        remove(workspace / "monitor")
    if clear_processors:
        remove(workspace / "persona" / "processor")
        remove(workspace / "subagent" / "_cursors")
    if clear_wiki_index:
        remove(workspace / "persona" / "wiki" / "index")
        remove(workspace / "persona" / "wiki" / "wiki" / "graph.json")
    if clear_user_memory:
        for path in (
            workspace / "persona" / "events",
            workspace / "persona" / "sessions",
            workspace / "persona" / "memory",
            workspace / "persona" / "wiki",
            workspace / "persona" / "benative" / "sessions",
        ):
            remove(path)
    else:
        kept.extend([
            "persona/events",
            "persona/sessions",
            "persona/memory",
            "persona/wiki/wiki",
            "persona/wiki/raw",
            "persona/benative/sessions",
        ])

    return {"removed": removed, "kept": kept}


def export_session(workspace: Path, session_key: str, output_dir: Path) -> dict[str, str]:
    safe_key = session_key.replace(":", "_").replace("/", "_")
    target = output_dir / f"session-{safe_key}"
    target.mkdir(parents=True, exist_ok=True)
    copied = _copy_existing(
        workspace,
        target,
        [
            workspace / "persona" / "sessions" / safe_key,
            workspace / "persona" / "benative" / "sessions" / session_key,
        ],
    )
    _write_manifest(target, "session", workspace, copied)
    return {"output": str(target), "copied": str(len(copied))}


def export_mode_artifacts(workspace: Path, mode: str, output_dir: Path) -> dict[str, str]:
    target = output_dir / f"mode-{mode}-artifacts"
    target.mkdir(parents=True, exist_ok=True)
    copied = _copy_existing(
        workspace,
        target,
        [
            workspace / "persona" / "processor" / mode,
            workspace / "mode" / mode,
        ],
    )
    _write_manifest(target, f"mode:{mode}", workspace, copied)
    return {"output": str(target), "copied": str(len(copied))}


def export_wiki(workspace: Path, output_dir: Path) -> dict[str, str]:
    target = output_dir / "wiki-export"
    target.mkdir(parents=True, exist_ok=True)
    copied = _copy_existing(
        workspace,
        target,
        [
            workspace / "persona" / "wiki" / "wiki",
            workspace / "persona" / "wiki" / "raw",
            workspace / "persona" / "wiki" / "state" / "sync_log.jsonl",
            workspace / "persona" / "wiki" / "state" / "queue.jsonl",
        ],
    )
    _write_manifest(target, "wiki", workspace, copied)
    return {"output": str(target), "copied": str(len(copied))}


def _copy_existing(workspace: Path, target: Path, paths: Iterable[Path]) -> list[str]:
    copied: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        rel = Path(_rel(path, workspace))
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(path, dest)
        else:
            shutil.copy2(path, dest)
        copied.append(rel.as_posix())
    return copied


def _write_manifest(target: Path, kind: str, workspace: Path, copied: list[str]) -> None:
    payload = {
        "kind": kind,
        "workspace": str(workspace),
        "created_at": datetime.now().isoformat(),
        "copied": copied,
    }
    (target / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _rel(path: Path, workspace: Path) -> str:
    try:
        return path.relative_to(workspace).as_posix()
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    reset = sub.add_parser("reset-dev")
    reset.add_argument("--monitor", action="store_true")
    reset.add_argument("--processors", action="store_true")
    reset.add_argument("--wiki-index", action="store_true")
    reset.add_argument("--clear-user-memory", action="store_true")

    export_session_cmd = sub.add_parser("export-session")
    export_session_cmd.add_argument("session_key")
    export_session_cmd.add_argument("--output-dir", type=Path, required=True)

    export_mode_cmd = sub.add_parser("export-mode-artifacts")
    export_mode_cmd.add_argument("mode")
    export_mode_cmd.add_argument("--output-dir", type=Path, required=True)

    export_wiki_cmd = sub.add_parser("export-wiki")
    export_wiki_cmd.add_argument("--output-dir", type=Path, required=True)

    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if args.command == "reset-dev":
        result = reset_dev_data(
            workspace,
            clear_monitor=args.monitor,
            clear_processors=args.processors,
            clear_wiki_index=args.wiki_index,
            clear_user_memory=args.clear_user_memory,
        )
    elif args.command == "export-session":
        result = export_session(workspace, args.session_key, args.output_dir.resolve())
    elif args.command == "export-mode-artifacts":
        result = export_mode_artifacts(workspace, args.mode, args.output_dir.resolve())
    elif args.command == "export-wiki":
        result = export_wiki(workspace, args.output_dir.resolve())
    else:
        raise SystemExit(f"unknown command: {args.command}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
