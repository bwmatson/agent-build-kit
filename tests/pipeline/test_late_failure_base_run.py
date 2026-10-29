"""The run of a late-failed check's tests on the default branch (spec: merged-waits-for-ci).

It is the repo's own unit-test, with the repo's profile, and the repository's turn is taken only
to add and remove the worktree. A base that cannot be reached leaves the unit settling.
"""

import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.cli.pipeline import build_repo_unit_test
from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import SETTLING
from tests.conftest import make_installation
from tests.factories import commit, init_repo, stored_unit


class Runner:
    """Answers every command as passed, and says what ran and where the turn stood."""

    def __init__(self, seen: list[str]) -> None:
        self.ran: list[list[str]] = []
        self.seen = seen

    def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        self.ran.append(command)
        self.seen.append("run")
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture
def node_repo(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "checkouts" / "app")
    commit(repo, "package.json", '{"name": "app"}')
    return repo


def passes_with(tmp_path: Path, repo: Path, turns: list[str], runner: Runner):
    inst = make_installation(
        tmp_path / "planning",
        repos={"app": {"path": str(repo), "slug": "example/app", "profile": "node-npm"}},
    )

    @contextmanager
    def turn(name: str) -> Iterator[None]:
        turns.append(f"enter {name}")
        yield
        turns.append(f"leave {name}")

    return events.build_base_passes(
        {"app": repo},
        unit_test_of=lambda name: build_repo_unit_test(inst, name, log=lambda m: None, run=runner),
        turn=turn,
    )


def test_a_node_shaped_repo_is_tested_with_its_own_profile_and_the_turn_wraps_only_the_worktree(
    tmp_path: Path, node_repo: Path
) -> None:
    seen: list[str] = []
    runner = Runner(seen)
    passes = passes_with(tmp_path, node_repo, seen, runner)

    assert passes(stored_unit("add-marker/1"), "FAILED src/a.test.ts") is True

    commands = [" ".join(command) for command in runner.ran]
    assert any("vitest" in command for command in commands)
    assert not any("pytest" in command for command in commands)
    first, last = seen.index("run"), len(seen) - 1 - seen[::-1].index("run")
    assert seen[:first].count("enter app") == seen[:first].count("leave app") >= 1
    assert seen[last + 1 :].count("enter app") == seen[last + 1 :].count("leave app") >= 1
    assert not any(step.startswith(("enter", "leave")) for step in seen[first : last + 1])


def test_a_base_that_cannot_be_reached_is_not_an_answer(tmp_path: Path, node_repo: Path) -> None:
    runner = Runner([])
    passes = passes_with(tmp_path, node_repo, [], runner)
    unit = stored_unit("add-marker/1", repo="app")
    # A repository with no commit on `main` to resolve.
    empty = init_repo(tmp_path / "empty")
    broken = events.build_base_passes(
        {"app": empty},
        unit_test_of=lambda name: lambda **kwargs: (True, ""),
        log=lambda m: None,
    )

    assert broken(unit, "") is None
    assert runner.ran == []
    assert passes(unit, "") is True


def test_a_late_check_with_no_answer_from_the_base_leaves_the_unit_settling(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")
    events.on_late_check(
        4,
        repo="app",
        pull=PullRequest(number=4, head="spec/add-marker/1", base="main", state="merged"),
        store=store,
        base_passes=lambda unit, logs: None,
        log=lambda m: None,
    )

    assert store.get("add-marker/1").state == SETTLING
