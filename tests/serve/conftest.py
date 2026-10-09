from __future__ import annotations

import os
import signal
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.serve.server import start_server
from tests.conftest import make_installation


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    # Worktrees under the test's own directory: by default they sit under the home directory
    # by the planning root's name, a path every run of the suite on the machine would share,
    # and a `claude` working in it would read as holding a session in another run's test.
    installation = make_installation(
        tmp_path / "planning", planning={"worktree_root": str(tmp_path / "worktrees")}
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return installation


@pytest.fixture
def api(inst: Installation) -> Iterator[httpx.Client]:
    """A client of a server running over `inst`."""
    with start_server(inst) as server, httpx.Client(base_url=server.url) as client:
        yield client


@pytest.fixture
def new_york_clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The host clock at UTC-5 all year, so a log's local stamps differ from UTC."""
    monkeypatch.setenv("TZ", "EST5")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture(autouse=True)
def no_real_claude_sessions(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sessions page lists Claude Code's sessions: never the machine's own. After
    `inst`, whose settings reload would undo it."""
    from agent_build_kit.settings import settings

    empty = tmp_path / "empty-claude-home"
    empty.mkdir()
    monkeypatch.setattr(settings, "claude_home", empty)


@pytest.fixture(autouse=True)
def no_agent_outlives_its_test(tmp_path: Path) -> Iterator[None]:
    """A fake agent left waiting for an answer is killed with its test. Its arguments name
    the session ids it holds, and the next test's sessions page would see it as a process
    that has them open."""
    yield
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            arguments = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if str(tmp_path).encode() in b" ".join(arguments):
            try:
                os.kill(int(entry.name), signal.SIGKILL)
            except OSError:
                pass
