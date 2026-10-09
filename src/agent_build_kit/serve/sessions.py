"""Sessions started elsewhere: the ones Claude Code keeps on disk, and which process holds one."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_build_kit.model import Frozen
from agent_build_kit.settings import settings


class ClaudeSession(Frozen):
    id: str
    path: Path
    cwd: str
    title: str
    updated: str


def claude_home() -> Path:
    return settings.claude_home or Path.home() / ".claude"


def _arguments(entry: Path) -> list[bytes] | None:
    try:
        return (entry / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return None


def _parent(pid: int) -> int:
    """The process that started `pid`, or 0."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return 0
    return int(stat[stat.rindex(")") + 2 :].split()[1])


def _is_ours(pid: int, proc: Path) -> bool:
    """Whether this process started `pid`, however many generations back: an agent the
    server runs is not an editor holding a session."""
    if proc != Path("/proc"):
        return False
    me = os.getpid()
    while pid > 1:
        pid = _parent(pid)
        if pid == me:
            return True
    return False


def _runs_claude(arguments: list[bytes]) -> bool:
    """Whether the process is Claude Code: `claude` itself, or a runtime started with its
    script as an argument."""
    return any(Path(argument.decode(errors="replace")).name == "claude" for argument in arguments)


def holding_pids(
    session_id: str, *, cwd: str = "", newest: bool = False, proc: Path = Path("/proc")
) -> list[int]:
    """The processes that have the session open: those with `session_id` among their
    arguments, as an editor running `claude --resume ID` has it, and, when `newest` says the
    session is the latest one of its directory `cwd`, a `claude` process working in that
    directory, which keeps its session without naming it."""
    found: list[int] = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit() or (arguments := _arguments(entry)) is None:
            continue
        pid = int(entry.name)
        if session_id.encode() in arguments:
            holds = True
        elif newest and cwd and _runs_claude(arguments):
            try:
                holds = (entry / "cwd").resolve() == Path(cwd).resolve()
            except OSError:
                continue
        else:
            continue
        if holds and not _is_ours(pid, proc):
            found.append(pid)
    return sorted(found)


def _lines(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open(errors="replace") as file:
            for line in file:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if isinstance(item, dict):
                    yield item
    except OSError:
        return


def _blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    return []


def claude_events(path: Path) -> list[dict[str, Any]]:
    """A session file as the events the sessions page shows: what was said by whom,
    with the tool calls and their results."""
    return list(_events(path))


def _events(path: Path) -> Iterable[dict[str, Any]]:
    for item in _lines(path):
        role = item.get("type")
        message = item.get("message")
        if role not in ("user", "assistant") or not isinstance(message, dict):
            continue
        for block in _blocks(message):
            match block.get("type"):
                case "text" if str(block.get("text", "")).strip():
                    yield {"kind": "text", "role": role, "text": block["text"]}
                case "thinking" if str(block.get("thinking", "")).strip():
                    yield {"kind": "reasoning", "role": role, "text": block["thinking"]}
                case "tool_use":
                    yield {
                        "kind": "tool_call",
                        "role": role,
                        "tool": str(block.get("name", "")),
                        "call": str(block.get("id", "")),
                        "input": block.get("input") or {},
                    }
                case "tool_result":
                    result = block.get("content")
                    text = (
                        result
                        if isinstance(result, str)
                        else "\n".join(
                            str(part.get("text", "")) for part in result if isinstance(part, dict)
                        )
                        if isinstance(result, list)
                        else ""
                    )
                    yield {
                        "kind": "tool_result",
                        "role": role,
                        "call": str(block.get("tool_use_id", "")),
                        "text": text,
                    }


def claude_sessions(home: Path) -> list[ClaudeSession]:
    """Every session under `home`'s `projects/<directory>/<id>.jsonl`, newest first."""
    found: list[ClaudeSession] = []
    for path in (home / "projects").glob("*/*.jsonl"):
        cwd = ""
        for item in _lines(path):
            cwd = cwd or str(item.get("cwd") or "")
            if cwd:
                break
        title = next(
            (
                str(event["text"]).strip().splitlines()[0]
                for event in _events(path)
                if event["kind"] == "text" and event["role"] == "user"
            ),
            "",
        )
        try:
            updated = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        except OSError:
            continue
        found.append(ClaudeSession(id=path.stem, path=path, cwd=cwd, title=title, updated=updated))
    return sorted(found, key=lambda s: s.updated, reverse=True)
