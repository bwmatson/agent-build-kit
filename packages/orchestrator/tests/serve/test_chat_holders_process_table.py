"""The chat object's lookups of who holds a session read a process table they are given, the
machine's by default."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.serve.chat import Chat
from tests.chat_serving import holding_process


@pytest.fixture
def chat(inst: Installation) -> Chat:
    return Chat(inst, units=lambda: [], recorded_session=lambda unit_id: None)


def table(root: Path, entries: dict[int, list[str]]) -> Path:
    for pid, arguments in entries.items():
        (root / str(pid)).mkdir(parents=True)
        (root / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in arguments) + b"\0")
    return root


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
) -> None:
    session_id = new_session_id()
    empty = tmp_path / "empty-proc"
    empty.mkdir()

    with holding_process(session_id):
        assert chat.holders(session_id, proc=empty) == []


def test_holders_find_a_real_detached_process_and_only_its_own_id(
    chat: Chat, new_session_id: Callable[[], str]
) -> None:
    mine, other = new_session_id(), new_session_id()

    with holding_process(mine) as pid:
        assert chat.holders(mine) == [pid]
        assert chat.holders(other) == []


def test_claude_holders_find_a_real_detached_process_and_only_its_own_id(
    chat: Chat, new_session_id: Callable[[], str]
) -> None:
    mine, other = new_session_id(), new_session_id()

    with holding_process(mine) as pid:
        assert chat.claude_holders(mine) == [pid]
        assert chat.claude_holders(other) == []
