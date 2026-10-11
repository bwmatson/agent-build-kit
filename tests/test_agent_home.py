"""The scratch agent home an acceptance test gives its agent, and the precondition that the agent
lists the session a later step resumes."""

from __future__ import annotations

import logging
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.runtimes.acp import AcpRuntime
from tests.agent_home import (
    HOME_FILES,
    HOME_VAR,
    REAL_HOME,
    AgentHome,
    agent_home,
    assert_session_listed,
)
from tests.forges.github_server import FakeGitHub
from tests.forges.process_host import process_env
from tests.runtimes.acp_agent import use_agent

AGENT_VAR = "FAKE_AGENT_HOME"
NAMES = ("config.yaml", ".env", "auth.json")
MARKER = "secret-marker-7f3a"


@pytest.fixture
def real_home(tmp_path: Path) -> Path:
    home = tmp_path / "real"
    home.mkdir()
    for name in NAMES:
        (home / name).write_text(f"{MARKER} {name}")
    (home / "state.db").write_text("the real store")
    return home


@pytest.fixture
def configured(real_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(HOME_VAR, AGENT_VAR)
    monkeypatch.setenv(REAL_HOME, str(real_home))
    monkeypatch.setenv(HOME_FILES, ",".join(NAMES))
    return real_home


class _Factory:
    """A temporary-directory factory that hands out a given directory, or counts its calls."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory
        self.calls = 0

    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        self.calls += 1
        assert self.directory is not None, "no directory should have been made"
        return self.directory


def test_the_scratch_home_holds_exactly_one_link_per_listed_name(
    configured: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    home = agent_home(tmp_path_factory)

    assert isinstance(home, AgentHome)
    assert home.path is not None
    assert stat.S_IMODE(home.path.stat().st_mode) == 0o700
    assert sorted(entry.name for entry in home.path.iterdir()) == sorted(NAMES)
    assert sorted(home.linked) == sorted(NAMES)
    for name in NAMES:
        link = home.path / name
        assert link.is_symlink()
        assert link.resolve() == (configured / name).resolve()
    assert home.env == {AGENT_VAR: str(home.path)}


def test_a_link_never_points_inside_the_scratch_home(
    configured: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    home = agent_home(tmp_path_factory)

    assert home.path is not None
    for entry in home.path.iterdir():
        assert not entry.resolve().is_relative_to(home.path.resolve())


def test_the_real_home_is_never_the_scratch_home(
    configured: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(scratch)
    monkeypatch.setenv(REAL_HOME, str(alias))

    with pytest.raises(AssertionError):
        agent_home(_Factory(scratch))


def test_a_real_home_that_contains_the_scratch_home_is_refused(
    configured: Path,
) -> None:
    scratch = configured / "nested" / "scratch"
    scratch.mkdir(parents=True)

    with pytest.raises(AssertionError):
        agent_home(_Factory(scratch))


@pytest.mark.parametrize("value", [None, ""])
def test_an_unset_home_variable_changes_nothing(
    value: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    if value is None:
        monkeypatch.delenv(HOME_VAR, raising=False)
    else:
        monkeypatch.setenv(HOME_VAR, value)
    monkeypatch.setenv(REAL_HOME, "/nonexistent/real/home")
    monkeypatch.setenv(HOME_FILES, "no-such-file")
    factory = _Factory()

    home = agent_home(factory)

    assert home.env == {}
    assert home.path is None
    assert home.linked == ()
    assert factory.calls == 0


def test_a_listed_file_missing_from_the_real_home_fails_naming_both(
    configured: Path, tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(HOME_FILES, "config.yaml,gone.json")

    with pytest.raises(AssertionError) as caught:
        agent_home(tmp_path_factory)

    assert "gone.json" in str(caught.value)
    assert str(configured) in str(caught.value)


@pytest.mark.parametrize(
    "name", ["subdir", "a/b", "../config.yaml", "state.db", "state.db-wal", "state.db-shm"]
)
def test_a_directory_a_path_or_the_state_database_is_refused(
    name: str,
    configured: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (configured / "subdir").mkdir()
    (configured / "state.db-wal").write_text("wal")
    (configured / "state.db-shm").write_text("shm")
    monkeypatch.setenv(HOME_FILES, f"config.yaml,{name}")

    with pytest.raises(AssertionError):
        agent_home(tmp_path_factory)


@pytest.mark.parametrize("missing", [REAL_HOME, HOME_FILES])
def test_a_missing_companion_variable_fails_naming_it(
    missing: str,
    configured: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(missing)

    with pytest.raises(AssertionError, match=missing):
        agent_home(tmp_path_factory)


def test_the_log_names_the_linked_files_and_never_their_contents(
    configured: Path,
    tmp_path_factory: pytest.TempPathFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        agent_home(tmp_path_factory)

    for name in NAMES:
        assert name in caplog.text
    assert MARKER not in caplog.text


def test_a_listed_session_passes(tmp_path: Path) -> None:
    cwd = tmp_path / "worktree"
    cwd.mkdir()
    use_agent(tmp_path / "agent.jsonl", resume=True, list_sessions=True, sessions=("sess_one",))

    assert_session_listed(AcpRuntime(), "sess_one", cwd)


@pytest.mark.parametrize("held", [(), ("sess_other",)])
def test_an_unlisted_session_fails_naming_the_cause(held: tuple[str, ...], tmp_path: Path) -> None:
    cwd = tmp_path / "worktree"
    cwd.mkdir()
    use_agent(tmp_path / "agent.jsonl", resume=True, list_sessions=True, sessions=held)

    with pytest.raises(AssertionError) as caught:
        assert_session_listed(AcpRuntime(), "sess_one", cwd)

    message = str(caught.value)
    assert "sess_one" in message
    assert str(cwd) in message
    assert "session store" in message
    for variable in (HOME_VAR, REAL_HOME, HOME_FILES):
        assert variable in message


# A stand-in for `abk tick` that starts the agent command below it, and the agent: a command that
# writes what it reads from its home variable to a file.
_TICK = "import subprocess, sys\nsubprocess.run(sys.argv[1:], check=True)\n"
_AGENT = "import os, sys\nopen(sys.argv[1], 'w').write(os.environ.get(sys.argv[2], '<unset>'))\n"


def _agent_sees(env: dict[str, str], tmp_path: Path, variable: str) -> str:
    """What the fake agent, started below the stand-in tick, reads from `variable`."""
    tick, agent, seen = tmp_path / "tick.py", tmp_path / "agent.py", tmp_path / "seen.txt"
    tick.write_text(_TICK)
    agent.write_text(_AGENT)
    argv = [sys.executable, str(tick), sys.executable, str(agent), str(seen), variable]
    subprocess.run(argv, env=env, check=True)
    return seen.read_text()


def test_the_scratch_path_reaches_the_agent_below_the_tick_process(
    configured: Path,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    github_server: FakeGitHub,
) -> None:
    home = agent_home(tmp_path_factory)
    env = {**process_env(github_server, tmp_path / "bin", tmp_path / "calls"), **home.env}

    assert _agent_sees(env, tmp_path, AGENT_VAR) == str(home.path)


def test_with_the_variable_unset_the_environment_passes_through_unchanged(
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
    github_server: FakeGitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HOME_VAR, raising=False)
    monkeypatch.setenv(AGENT_VAR, "the-tests-own-value")
    home = agent_home(tmp_path_factory)
    env = {**process_env(github_server, tmp_path / "bin", tmp_path / "calls"), **home.env}

    assert _agent_sees(env, tmp_path, AGENT_VAR) == "the-tests-own-value"
