"""The chat object's lookups of who holds a session read a process table they are given, the
machine's by default."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.serve.chat import Chat

SLEEP = "import time; time.sleep(60)"
# Starts the session in its own process group and exits, so its parent is not this test.
DETACH = (
    "import subprocess, sys;"
    "p = subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]],"
    " start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,"
    " stderr=subprocess.DEVNULL);"
    "print(p.pid)"
)


@pytest.fixture
def chat(inst: Installation) -> Chat:
    return Chat(inst, units=lambda: [], recorded_session=lambda unit_id: None)


def table(root: Path, entries: dict[int, list[str]]) -> Path:
    for pid, arguments in entries.items():
        (root / str(pid)).mkdir(parents=True)
        (root / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in arguments) + b"\0")
    return root


@pytest.fixture
def detached() -> Iterator[Callable[[str], int]]:
    started: list[int] = []

    def start(session_id: str) -> int:
        out = subprocess.run(
            [sys.executable, "-c", DETACH, SLEEP, session_id],
            capture_output=True,
            text=True,
            check=True,
        )
        started.append(int(out.stdout))
        return started[-1]

    yield start
    for pid in started:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def test_holders_answer_from_the_given_table(
    chat: Chat, tmp_path: Path, new_session_id: Callable[[], str]
) -> None:
    mine, other = new_session_id(), new_session_id()
    proc = table(
        tmp_path / "proc",
        {4101: ["claude", "--resume", mine], 4102: ["claude", "--resume", other]},
    )

    assert chat.holders(mine, proc=proc) == [4101]
    assert chat.holders(new_session_id(), proc=proc) == []


def test_claude_holders_and_session_holders_answer_from_the_given_table(
    chat: Chat, tmp_path: Path, new_session_id: Callable[[], str]
) -> None:
    mine = new_session_id()
    proc = table(tmp_path / "proc", {4201: ["claude", "--resume", mine]})

    assert chat.claude_holders(mine, proc=proc) == [4201]
    assert chat.session_holders("claude_code", mine, proc=proc) == [4201]
    assert chat.session_holders("acp", mine, proc=proc) == [4201]


def test_a_private_table_hides_the_machines_processes(
    chat: Chat,
    tmp_path: Path,
    new_session_id: Callable[[], str],
    detached: Callable[[str], int],
) -> None:
    session_id = new_session_id()
    detached(session_id)
    empty = tmp_path / "empty-proc"
    empty.mkdir()

    assert chat.holders(session_id, proc=empty) == []


def test_holders_find_a_real_detached_process_and_only_its_own_id(
    chat: Chat, new_session_id: Callable[[], str], detached: Callable[[str], int]
) -> None:
    mine, other = new_session_id(), new_session_id()
    pid = detached(mine)

    assert chat.holders(mine) == [pid]
    assert chat.holders(other) == []


def test_claude_holders_find_a_real_detached_process_and_only_its_own_id(
    chat: Chat, new_session_id: Callable[[], str], detached: Callable[[str], int]
) -> None:
    mine, other = new_session_id(), new_session_id()
    pid = detached(mine)

    assert chat.claude_holders(mine) == [pid]
    assert chat.claude_holders(other) == []
