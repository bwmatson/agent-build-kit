"""The push gate, end to end.

`check_branch` is the one call the PreToolUse hook makes, so these tests build
real branches and let it run real commands in a real worktree. The commands
are cheap stand-ins for pre-commit and pytest, injected by monkeypatching the
two command templates — running the actual tools here would test uv's cache
more than it tests the gate.
"""

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.check_runner import CheckCache
from agent_build_kit.pipeline.gate import check_branch
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.factories import git, init_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    return work


def commit(repo: Path, message: str, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def tests_first_branch(repo: Path) -> None:
    commit(repo, "test: covers it", {"tests/test_thing.py": "def test_x(): assert False\n"})
    commit(repo, "feat: implements it", {"src/thing.py": "x = 1\n"})


@pytest.fixture
def fake_commands(monkeypatch: pytest.MonkeyPatch):
    """Stand in for pre-commit and pytest with scripted output."""

    def configure(*, clean_exit: int = 0, red_output: str, red_exit: int = 1) -> None:
        class Scripted:
            """The Python profile with its two shell-outs replaced."""

            def clean_command(self) -> str:
                return f"exit {clean_exit}"

            def red_command(self, files: list[str]) -> str:
                return f"printf '%s' {red_output!r} && exit {red_exit}"

            def __getattr__(self, name):
                return getattr(PYTHON, name)

        monkeypatch.setattr(profiles, "get", lambda name: Scripted())

    return configure


FAILED = "1 failed in 0.01s\nFAILED tests/test_thing.py::test_x - assert 0 == 1\n"
PASSED = "2 passed in 0.01s\n"


def test_a_well_formed_branch_passes(repo: Path, fake_commands) -> None:
    tests_first_branch(repo)
    fake_commands(red_output=FAILED)

    assert check_branch(repo, "main") == []


def test_a_structural_problem_short_circuits(repo: Path, fake_commands) -> None:
    """If the shape is wrong, "which commit is the tests commit" isn't a
    meaningful question yet, so nothing is run."""
    commit(repo, "feat: all at once", {"src/thing.py": "def x():\n    return 1\n"})
    fake_commands(red_output=PASSED)

    problems = check_branch(repo, "main")

    assert problems
    assert "first commit" in problems[0] or "no implementation" in problems[0]


def test_tests_that_passed_at_the_tests_commit_block_the_push(repo: Path, fake_commands) -> None:
    """The case the gate exists for."""
    tests_first_branch(repo)
    fake_commands(red_output=PASSED, red_exit=0)

    problems = check_branch(repo, "main")

    assert any("passed at the tests commit" in problem for problem in problems)


def test_lint_failing_at_the_tests_commit_blocks_the_push(repo: Path, fake_commands) -> None:
    tests_first_branch(repo)
    fake_commands(clean_exit=1, red_output=FAILED)

    problems = check_branch(repo, "main")

    assert any("lint/format" in problem for problem in problems)


def test_a_cached_pass_skips_the_work(repo: Path, fake_commands, tmp_path: Path) -> None:
    """A restack re-pushes commits whose content nothing has changed; re-running
    the suite for each of them would make every restack slower than the work."""
    tests_first_branch(repo)
    cache = CheckCache(tmp_path / "cache.json")
    fake_commands(red_output=FAILED)
    assert check_branch(repo, "main", cache=cache) == []

    # Now make the commands fail loudly: a cache hit means they never run.
    fake_commands(clean_exit=1, red_output=PASSED, red_exit=0)

    assert check_branch(repo, "main", cache=cache) == []


def test_a_cached_failure_still_blocks(repo: Path, fake_commands, tmp_path: Path) -> None:
    tests_first_branch(repo)
    cache = CheckCache(tmp_path / "cache.json")
    fake_commands(red_output=PASSED, red_exit=0)
    assert check_branch(repo, "main", cache=cache) != []

    fake_commands(red_output=FAILED)

    assert check_branch(repo, "main", cache=cache) != []


def test_the_gate_does_not_touch_the_working_tree(repo: Path, fake_commands) -> None:
    """A gate that edits what it is judging is no longer a gate."""
    tests_first_branch(repo)
    fake_commands(red_output=FAILED)

    check_branch(repo, "main")

    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "spec/change/1-unit"
