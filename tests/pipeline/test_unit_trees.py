"""Every caller that needs a unit's worktree finds it through git, wherever under the worktree
root it is (spec: unit-worktrees).

Two repos: `lib`, with `path: .` in an installation whose root is a folder named `worktree`, and
`app`, at a folder named `app-src`. Each unit's branch is checked out under a folder neither
repo's name gives, as a layout of an earlier release left it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.retire_cmd import retire
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import attach
from agent_build_kit.pipeline.manual_steps import evaluate_manual_steps
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED, ManualStep
from agent_build_kit.pipeline.verify import Verification
from agent_build_kit.serve.review import unit_worktree
from tests.conftest import make_installation
from tests.factories import commit_files, git, init_repo, stored_unit
from tests.planning_worktree_support import add_pipeline_worktree, working_copy_of

EARLIER = "earlier"
NOW = datetime(2026, 10, 11, tzinfo=UTC)
SLUG = "flip-marker"


@dataclass
class World:
    inst: Installation
    store: UnitStore
    trees: dict[str, Path]  # repo -> its unit's worktree, under the folder `earlier`

    def unit(self, repo: str) -> StoredUnit:
        return self.store.get(f"{repo}-change/1")


@pytest.fixture
def world(tmp_path: Path) -> World:
    _, lib = working_copy_of(tmp_path, origin=False, name="lib")
    root = add_pipeline_worktree(lib, tmp_path / "worktree")
    app = init_repo(tmp_path / "app-src")
    commit_files(app, "start", {"README.md": "app\n"})
    inst = make_installation(
        root,
        repos={
            "lib": {"path": ".", "slug": "example/lib"},
            "app": {"path": str(app), "slug": "example/app"},
        },
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
    )
    store = UnitStore(inst.state_dir / "units.json")
    trees: dict[str, Path] = {}
    for repo in ("lib", "app"):
        branch = f"spec/{repo}-change/1"
        tree = inst.worktree_root / EARLIER / f"spec_{repo}_change_1"
        tree.parent.mkdir(parents=True, exist_ok=True)
        git(inst.checkouts[repo], "worktree", "add", "-q", "-b", branch, str(tree), "HEAD")
        trees[repo] = tree
        store.upsert([stored_unit(f"{repo}-change/1", change=f"{repo}-change", repo=repo)])
        store.set_state(f"{repo}-change/1", PLANNED, branch=branch)
    return World(inst, store, trees)


@pytest.mark.parametrize("repo", ["lib", "app"])
def test_attach_finds_the_worktree_under_an_earlier_folder(world: World, repo: str) -> None:
    assert attach.worktree_of(world.inst, world.unit(repo)) == world.trees[repo]


@pytest.mark.parametrize("repo", ["lib", "app"])
def test_the_review_page_finds_the_worktree_under_an_earlier_folder(
    world: World, repo: str
) -> None:
    assert unit_worktree(world.inst, world.unit(repo)) == world.trees[repo]


@pytest.mark.parametrize("repo", ["lib", "app"])
def test_a_manual_step_check_runs_in_the_worktree_under_an_earlier_folder(
    world: World, repo: str
) -> None:
    check = f".abk/manual/{SLUG}.sh"
    script = world.trees[repo] / check
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    step = ManualStep(slug=SLUG, text="Flip it", runbook="docs/r.md#x", check=check)
    unit_id = world.unit(repo).id
    world.store.set_manual_steps(unit_id, [step])

    evaluate_manual_steps(world.inst, world.store, now=NOW)

    assert world.store.get(unit_id).manual_steps[0].done, "the check was found in the worktree"


def test_the_scratch_of_each_units_worktree_is_cleared_when_its_change_is_archived(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: dict[str, list[Path]] = {}

    def verified(inst: Installation, change: str, units: list, **kwargs: Any) -> Verification:
        return Verification(change=change, passed=True)

    def archiving(units: list, **kwargs: Any) -> list[str]:
        for change in ("lib-change", "app-change"):
            asked[change] = kwargs["worktrees"](change)
        return []

    monkeypatch.setattr(cli, "verify_one", verified)
    monkeypatch.setattr(cli, "archive_ready_changes", archiving)

    cli.cmd_verify(argparse.Namespace(change="lib-change"), world.inst)

    assert asked == {"lib-change": [world.trees["lib"]], "app-change": [world.trees["app"]]}


def test_retire_sees_the_uncommitted_work_in_a_worktree_under_an_earlier_folder(
    world: World,
) -> None:
    (world.trees["app"] / "half-done.txt").write_text("not committed\n")
    said: list[str] = []

    code = retire(
        world.inst,
        world.unit("app").id,
        say=lambda text, **kwargs: said.append(text),
        reason="test",
        delete_branch=True,
    )

    assert code == 1
    assert any("uncommitted" in line for line in said)
    assert (world.trees["app"] / "half-done.txt").exists()


@pytest.mark.parametrize("repo", ["lib", "app"])
def test_a_restack_checks_run_as_the_repo_whose_worktree_they_run_in(
    world: World, monkeypatch: pytest.MonkeyPatch, repo: str
) -> None:
    hooks: dict[str, Any] = {}
    monkeypatch.setattr(cli, "build_restack", lambda **kwargs: hooks.update(kwargs))
    built: list[str] = []

    def unit_test(**kwargs: Any):
        built.append(kwargs["repo"].slug)
        return lambda *, cwd, base, moved_from=None: (True, "")

    monkeypatch.setattr(cli, "build_unit_test", unit_test)
    cli.build_stack_moves(world.store, world.inst)
    # Where a temporary tree for the repo goes: under the folder its name gives.
    tree = world.inst.worktree_root / repo / "restack-spec_x_1"
    tree.parent.mkdir(parents=True, exist_ok=True)
    git(world.inst.checkouts[repo], "worktree", "add", "-q", "--detach", str(tree), "HEAD")

    ok, _ = hooks["unit_test"](cwd=tree, base="main")

    assert ok
    assert built == [f"example/{repo}"]
