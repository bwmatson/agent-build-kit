"""The commit gate reads its branch through the shared git runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline import gate
from agent_build_kit.pipeline.gate import check_branch
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.factories import git, init_repo
from tests.git_runner_spy import spy_on_git

RED = "1 failed in 0.01s\\nFAILED tests/test_thing.py::test_x - assert 0"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    (work / "tests").mkdir()
    (work / "tests" / "test_thing.py").write_text("def test_x(): assert False\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "test: covers it")
    (work / "src").mkdir()
    (work / "src" / "thing.py").write_text("x = 1\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "feat: implements it")
    return work


@pytest.fixture(autouse=True)
def scripted_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    class Scripted:
        def clean_command(self) -> str:
            return "exit 0"

        def red_command(self, files: list[str], ids: list[str] | None = None) -> str:
            return f"printf '{RED}' && exit 1"

        def __getattr__(self, name):
            return getattr(PYTHON, name)

    monkeypatch.setattr(profiles, "get", lambda name: Scripted())


def test_the_branch_is_read_through_the_shared_runner(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = spy_on_git(monkeypatch, gate)

    assert check_branch(repo, "main") == []

    assert spy.calls[0] == ("rev-list", "--reverse", "main..HEAD")
    assert "show" in spy.subcommands()


def test_a_failing_read_still_raises_the_commands_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy_on_git(monkeypatch, gate, failing={"rev-list": "fatal: bad revision"})

    with pytest.raises(subprocess.CalledProcessError) as raised:
        check_branch(repo, "main")

    assert "bad revision" in raised.value.stderr
