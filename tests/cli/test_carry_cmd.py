"""`abk carry`: carry a unit that landed off the default branch onto it, on demand
(spec: landed-off-default-units-are-carried).

Real git in the retire scene's `app` checkout with an `origin`, and the code host stand-in."""

from __future__ import annotations

import pytest

from agent_build_kit.cli import main
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED
from tests.factories import commit_files, git
from tests.retire_scene import Scene, scene  # noqa: F401
from tests.review_approval import give_a_remote

UNIT = "feature/2"
CARRY_BRANCH = f"spec/{UNIT}/carry"


def landed_off_default(scene: Scene, state: str = HELD, **fields) -> str:  # noqa: F811
    """The unit's work as one commit on a branch that is not `main`, recorded as the unit's
    merge commit, with `main` pushed to an `origin`; the commit."""
    give_a_remote(scene.repo)
    git(scene.repo, "push", "-q", "origin", "main")
    git(scene.repo, "checkout", "-q", "-b", "spec/feature/1")
    commit_files(scene.repo, "unit work", {"unit.txt": "work\n"})
    sha = git(scene.repo, "rev-parse", "HEAD").strip()
    git(scene.repo, "checkout", "-q", "main")
    scene.add(UNIT, state, pr=2, merge_sha=sha, **fields)
    return sha


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    capsys.readouterr()
    code = main(["carry", *argv])
    seen = capsys.readouterr()
    return code, seen.out + seen.err


def held(scene: Scene) -> str:  # noqa: F811
    sha = landed_off_default(scene, HELD)
    scene.store.set_state(UNIT, HELD, cause=Cause.LANDED_OFF_DEFAULT)
    return sha


def test_carrying_a_held_unit_opens_the_pull_request_the_round_would(
    scene: Scene,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    held(scene)

    code, out = run(capsys, UNIT)

    unit = scene.unit(UNIT)
    assert [(c["head"], c["base"]) for c in scene.host.created] == [(CARRY_BRANCH, "main")]
    assert (unit.state, unit.cause) == (IN_REVIEW, Cause.CARRIED)
    assert code == 0


def test_a_dry_run_prints_the_commit_and_the_branch_and_writes_nothing(
    scene: Scene,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    sha = held(scene)
    before = scene.snapshot()

    code, out = run(capsys, UNIT, "--dry-run")

    assert sha in out and CARRY_BRANCH in out
    assert code == 0
    assert scene.snapshot() == before
    assert scene.host.created == []
    assert not git(scene.repo, "branch", "--list", CARRY_BRANCH).strip()


def test_repair_carries_a_unit_recorded_merged_with_a_commit_not_on_the_default_branch(
    scene: Scene,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    landed_off_default(scene, MERGED)

    code, out = run(capsys, UNIT, "--repair")

    assert code == 0, out
    assert [c["head"] for c in scene.host.created] == [CARRY_BRANCH]
    assert scene.unit(UNIT).state == IN_REVIEW


def test_landed_as_records_a_commit_of_the_default_branch_as_the_merge_commit(
    scene: Scene,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    landed_off_default(scene, MERGED)
    commit_files(scene.repo, "carries the work", {"unit.txt": "work\n"})
    git(scene.repo, "push", "-q", "origin", "main")
    carrying = git(scene.repo, "rev-parse", "HEAD").strip()

    code, out = run(capsys, UNIT, "--landed-as", carrying)

    assert code == 0, out
    assert scene.unit(UNIT).merge_sha == carrying


def test_landed_as_refuses_a_commit_that_is_not_on_the_default_branch(
    scene: Scene,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    off = landed_off_default(scene, MERGED)
    before = scene.snapshot()

    code, out = run(capsys, UNIT, "--landed-as", off)

    assert code == 1
    assert "default branch" in out
    assert scene.snapshot() == before


def test_a_unit_that_is_not_held_is_refused_naming_its_state(
    scene: Scene,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    landed_off_default(scene, IN_REVIEW)
    before = scene.snapshot()

    code, out = run(capsys, UNIT)

    assert code == 1
    assert IN_REVIEW in out
    assert scene.snapshot() == before
    assert scene.host.created == []


def test_repair_refuses_a_merged_unit_whose_commit_is_on_the_default_branch(
    scene: Scene,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    landed_off_default(scene, MERGED)
    commit_files(scene.repo, "on default", {"other.txt": "x\n"})
    git(scene.repo, "push", "-q", "origin", "main")
    on_default = git(scene.repo, "rev-parse", "HEAD").strip()
    scene.store.set_merge_record(UNIT, on_default, None)

    code, out = run(capsys, UNIT, "--repair")

    assert code == 1
    assert "default branch" in out
    assert scene.host.created == []
