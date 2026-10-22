"""`abk manual raise` (spec: manual-steps): a builder registers a step with a check script.

Each test runs the real command line from a real git worktree of a fixture repo on a unit's
branch, with the unit in the store, and checks what the store holds afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, RUNNING
from agent_build_kit.pipeline.wiring import allowed_tools
from agent_build_kit.profiles.python_uv import PROFILE
from agent_build_kit.tool_patterns import allows
from tests.conftest import make_installation
from tests.factories import git, init_repo, unit

UNIT = "feature/1"
SLUG = "pre-commit-config"
SCRIPT = f".abk/manual/{SLUG}.sh"
TEXT = "A person installs the pre-commit config"


@dataclass
class Tree:
    root: Path
    config: Path
    store: UnitStore

    def script(self, body: str, *, mode: int = 0o755, name: str = f"{SLUG}.sh") -> str:
        path = self.root / ".abk" / "manual" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(mode)
        return f".abk/manual/{name}"

    def raise_step(self, check: str, slug: str = SLUG) -> int:
        argv = ["manual", "raise", slug, "--text", TEXT, "--check", check]
        return main(["--config", str(self.config), *argv])

    def steps(self) -> tuple:
        return UnitStore(self.store.path).get(UNIT).manual_steps


def make_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str = "spec/") -> Tree:
    repo = init_repo(tmp_path / "app")
    (repo / "keep.txt").write_text("keep\n")
    git(repo, "add", "keep.txt")
    git(repo, "commit", "-q", "-m", "base")
    root = tmp_path / "trees" / "unit"
    git(repo, "worktree", "add", "-q", "-b", f"{prefix}{UNIT}", str(root))
    installation = make_installation(
        tmp_path / "planning",
        limits=dict(manual_check_seconds=1),
        git=dict(branch_prefix=prefix),
    )
    config = installation.root / "abk.yaml"
    config.write_text(dump(installation.config))
    store = UnitStore(installation.state_dir / "units.json")
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, RUNNING)
    monkeypatch.chdir(root)
    return Tree(root, config, store)


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tree:
    return make_tree(tmp_path, monkeypatch)


def test_a_worktree_on_the_installations_own_branch_prefix_is_its_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = make_tree(tmp_path, monkeypatch, prefix="agent/")
    check = tree.script("exit 1")

    code = tree.raise_step(check)

    assert code == 0
    assert [step.slug for step in tree.steps()] == [SLUG]


def test_a_raised_step_is_registered_on_the_unit_of_the_worktree(tree: Tree) -> None:
    check = tree.script("echo 'config missing'; exit 1")

    code = tree.raise_step(check)

    assert code == 0
    assert [(step.slug, step.text, step.check) for step in tree.steps()] == [(SLUG, TEXT, SCRIPT)]
    assert UnitStore(tree.store.path).get(UNIT).state in (RUNNING, PLANNED)


def test_a_check_that_already_passes_is_registered_and_not_marked_done(tree: Tree) -> None:
    check = tree.script("exit 0")

    code = tree.raise_step(check)

    assert code == 0
    assert [step.slug for step in tree.steps()] == [SLUG]
    assert (tree.root / SCRIPT).is_file()


def test_a_script_that_does_not_exist_is_refused_and_nothing_is_registered(
    tree: Tree, capsys: pytest.CaptureFixture[str]
) -> None:
    code = tree.raise_step(SCRIPT)

    assert code != 0
    assert SCRIPT in capsys.readouterr().err
    assert tree.steps() == ()


def test_a_script_that_is_not_executable_is_refused_and_nothing_is_registered(
    tree: Tree, capsys: pytest.CaptureFixture[str]
) -> None:
    check = tree.script("exit 1", mode=0o644)

    code = tree.raise_step(check)

    assert code != 0
    assert "executable" in capsys.readouterr().err
    assert tree.steps() == ()


def test_a_script_that_runs_past_the_timeout_is_refused_and_nothing_is_registered(
    tree: Tree, capsys: pytest.CaptureFixture[str]
) -> None:
    check = tree.script("exec sleep 30")

    code = tree.raise_step(check)

    assert code != 0
    assert "timeout" in capsys.readouterr().err.lower()
    assert tree.steps() == ()


def test_a_script_outside_the_manual_folder_is_refused(tree: Tree) -> None:
    (tree.root / "elsewhere.sh").write_text("#!/bin/sh\nexit 1\n")
    (tree.root / "elsewhere.sh").chmod(0o755)

    code = tree.raise_step("elsewhere.sh")

    assert code != 0
    assert tree.steps() == ()


def test_a_builder_may_run_the_raise_command() -> None:
    tools = allowed_tools(PROFILE, forges.get("github"))

    assert allows(tools, f"abk manual raise {SLUG} --text 'x' --check {SCRIPT}")
