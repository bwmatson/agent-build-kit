"""The split step keeps the held unit's branch tip under its superseded ref, in the unit's code
repo, before it supersedes the unit; a branch that cannot be kept supersedes nothing (spec:
unit-superseding)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import CLOSED, HELD
from agent_build_kit.pipeline.workspaces import superseded_ref
from tests.cli.replan_driver import Replan
from tests.factories import commit, init_repo
from tests.split_step_support import HELD_ID, correct, reply, scene

pytestmark = pytest.mark.usefixtures("scripted_engine")


def code_repo(run: Replan, *, with_branch: bool = True) -> tuple[Path, str]:
    """The held unit's code repo on disk, with its branch one commit past main and that commit."""
    repo = init_repo(run.inst.checkouts["app"])
    commit(repo, "base.txt")
    if not with_branch:
        return repo, ""
    git(repo, "checkout", "-q", "-b", f"spec/{HELD_ID}")
    tip = commit(repo, "work.txt")
    git(repo, "checkout", "-q", "main")
    return repo, tip


def test_the_old_tip_is_kept_under_the_ref_and_the_unit_is_superseded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    repo, tip = code_repo(run)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    assert git_out(repo, "rev-parse", superseded_ref(HELD_ID)) == tip
    old = run.store.get(HELD_ID)
    assert (old.state, old.cause) == (CLOSED, Cause.SUPERSEDED)


def test_a_branch_that_cannot_be_kept_supersedes_nothing_and_uses_no_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    repo, _ = code_repo(run, with_branch=False)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    held = run.store.get(HELD_ID)
    assert held.state == HELD and held.split_rounds_used == 0
    assert git(repo, "for-each-ref", "refs/spec-driven", check=False).stdout.strip() == ""
