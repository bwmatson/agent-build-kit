"""`abk red-check` (spec: tdd-loop): the tests step sees the build's red verdict before it finishes.

Each test runs the real command line from a real git worktree of a fixture repo on a unit's
branch, with the unit in the store and the red command scripted, and checks the exit, what is
printed and that the worktree is as it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.pipeline.red_check import Rule
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.conftest import make_installation
from tests.factories import git, init_repo, unit
from tests.junit_cases import failing, passing, printed
from tests.scripted_red import script_commands

UNIT = "feature/1"
NEW_TEST = "tests/test_new.py"
MODULE = "tests.test_new"
NEW_SOURCE = "def test_new():\n    assert False\n"
MISSING_STUB = ("tests.test_new", "test_new", "AttributeError: module 'thing' has no attribute 'f'")


@dataclass
class Tree:
    root: Path
    config: Path

    def run(self) -> int:
        return main(["--config", str(self.config), "red-check"])

    def snapshot(self) -> tuple[str, str, str, dict[str, str]]:
        """What the command must leave as it found it: `HEAD`, the index, the status and the
        files."""
        files = {
            str(path.relative_to(self.root)): path.read_text()
            for path in sorted(self.root.rglob("*"))
            if path.is_file() and ".git" not in path.relative_to(self.root).parts
        }
        return (
            git(self.root, "rev-parse", "HEAD"),
            git(self.root, "diff", "--cached"),
            git(self.root, "status", "--porcelain"),
            files,
        )


def make_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, branch: str = f"spec/{UNIT}"
) -> Tree:
    repo = init_repo(tmp_path / "app")
    (repo / "keep.txt").write_text("keep\n")
    git(repo, "add", "keep.txt")
    git(repo, "commit", "-q", "-m", "base")
    root = tmp_path / "trees" / "unit"
    git(repo, "worktree", "add", "-q", "-b", branch, str(root))
    installation = make_installation(tmp_path / "planning", builders=dict(stubbed_tdd_commits=True))
    config = installation.root / "abk.yaml"
    config.write_text(dump(installation.config))
    store = UnitStore(installation.state_dir / "units.json")
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, RUNNING)
    monkeypatch.chdir(root)
    return Tree(root, config)


def new_test_line(outcome: str) -> str:
    return f"{NEW_TEST}::test_new: {Rule.NEW.value}: must fail — {outcome}"


@pytest.mark.parametrize(
    ("cases", "exit_code", "printed_parts"),
    [
        pytest.param([failing(MODULE, "test_new")], 0, [new_test_line("failed")], id="red"),
        pytest.param(
            [passing(MODULE, "test_new")],
            1,
            [NEW_TEST + "::test_new", Rule.NEW.value, "must fail", "passed"],
            id="a new test that passes",
        ),
        pytest.param([MISSING_STUB], 1, ["stub"], id="a missing stub"),
    ],
)
def test_the_command_judges_the_new_tests_as_the_builds_red_check_does(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cases: list[tuple[str, str, str | None]],
    exit_code: int,
    printed_parts: list[str],
) -> None:
    tree = make_tree(tmp_path, monkeypatch)
    (tree.root / NEW_TEST).parent.mkdir(exist_ok=True)
    (tree.root / NEW_TEST).write_text(NEW_SOURCE)
    script_commands(monkeypatch, red_output=printed(cases), red_exit=1)
    before = tree.snapshot()

    code = tree.run()

    shown = capsys.readouterr().out
    assert code == exit_code
    for part in printed_parts:
        assert part in shown
    assert tree.snapshot() == before


def test_a_worktree_with_no_test_file_changed_is_refused_with_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree = make_tree(tmp_path, monkeypatch)
    (tree.root / "keep.txt").write_text("changed\n")
    script_commands(monkeypatch, red_output=printed([failing(MODULE, "test_new")]))
    before = tree.snapshot()

    code = tree.run()

    captured = capsys.readouterr()
    assert code == 2
    assert "no test file" in captured.err
    assert tree.snapshot() == before


def test_a_worktree_outside_a_units_branch_is_refused_with_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree = make_tree(tmp_path, monkeypatch, branch="scratch")
    (tree.root / NEW_TEST).parent.mkdir(exist_ok=True)
    (tree.root / NEW_TEST).write_text(NEW_SOURCE)
    script_commands(monkeypatch, red_output=printed([failing(MODULE, "test_new")]))
    before = tree.snapshot()

    code = tree.run()

    captured = capsys.readouterr()
    assert code == 2
    assert "scratch" in captured.err
    assert tree.snapshot() == before
