"""`abk doctor`'s landing checks: whether the forge deletes merged branches and agrees with
`delete_merged_branches`, and the units recorded `merged` with a commit that is not on the
default branch (spec: landed-off-default-units-are-carried).

Real git in the retire scene's `app` checkout with an `origin`, and the code host stand-in."""

from __future__ import annotations

import pytest

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import dump
from agent_build_kit.pipeline.units import MERGED
from tests.cli.test_doctor import Answers
from tests.factories import commit_files, git, which_all
from tests.retire_scene import Scene, scene  # noqa: F401
from tests.review_approval import give_a_remote

BRANCHES = "merged branches"
FALSE_MERGES = "merged units"
UNIT = "feature/2"


def checks(scene: Scene, name: str) -> list[Check]:  # noqa: F811
    found = run_doctor(scene.inst.root / "abk.yaml", run=Answers(), which=which_all)
    return [check for check in found if name in check.name]


def said(found: list[Check]) -> str:
    return " ".join(f"{check.detail} {check.fix}" for check in found)


def setting(scene: Scene, *, on: bool) -> None:  # noqa: F811
    """`delete_merged_branches` as given, in the `abk.yaml` the doctor loads."""
    config = scene.inst.config
    repos = {
        name: repo.model_copy(update={"delete_merged_branches": on})
        for name, repo in config.repos.items()
    }
    (scene.inst.root / "abk.yaml").write_text(dump(config.model_copy(update={"repos": repos})))


def recorded_merged(scene: Scene, *, on_default: bool) -> str:  # noqa: F811
    """A unit recorded `merged` with a commit of a side branch, and `main` pushed to an
    `origin`; the unit's work is on `main` too when `on_default`. The recorded commit."""
    give_a_remote(scene.repo)
    git(scene.repo, "push", "-q", "origin", "main")
    git(scene.repo, "checkout", "-q", "-b", "spec/feature/1")
    commit_files(scene.repo, "unit work", {"unit.txt": "work\n"})
    sha = git(scene.repo, "rev-parse", "HEAD").strip()
    git(scene.repo, "checkout", "-q", "main")
    if on_default:
        commit_files(scene.repo, "squashed", {"unit.txt": "work\n"})
    git(scene.repo, "push", "-q", "origin", "main")
    scene.add(UNIT, MERGED, pr=2, merge_sha=sha)
    return sha


@pytest.mark.parametrize(("forge_deletes", "on"), [(True, True), (False, True), (False, False)])
def test_a_forge_and_a_setting_that_agree_are_not_warned_about(
    scene: Scene,  # noqa: F811
    forge_deletes: bool,
    on: bool,
) -> None:
    scene.host.deletes_head_branch_on_merge = forge_deletes
    setting(scene, on=on)

    found = checks(scene, BRANCHES)

    assert found
    assert "app" in said(found)
    assert [c.status for c in found if c.status in ("warn", "FAIL")] == []


def test_a_forge_that_deletes_merged_branches_while_the_setting_is_off_is_a_warning(
    scene: Scene,  # noqa: F811
) -> None:
    scene.host.deletes_head_branch_on_merge = True
    setting(scene, on=False)

    found = checks(scene, BRANCHES)

    assert [c.status for c in found] == ["warn"]
    assert "app" in said(found)
    assert "delete_merged_branches" in said(found)


def test_a_merged_unit_whose_commit_is_not_on_the_default_branch_is_listed_with_the_repair(
    scene: Scene,  # noqa: F811
) -> None:
    sha = recorded_merged(scene, on_default=False)

    found = checks(scene, FALSE_MERGES)

    assert [c.status for c in found] == ["warn"]
    assert UNIT in said(found)
    assert f"abk carry --repair {UNIT}" in said(found)
    assert "--landed-as" not in said(found)
    assert sha[:7] in said(found)


def test_a_false_merge_whose_changes_are_on_the_default_branch_is_listed_with_landed_as(
    scene: Scene,  # noqa: F811
) -> None:
    sha = recorded_merged(scene, on_default=True)

    found = checks(scene, FALSE_MERGES)

    assert [c.status for c in found] == ["warn"]
    assert f"abk carry {UNIT} --landed-as" in said(found)
    assert "--repair" not in said(found)
    assert sha[:7] in said(found)


def test_a_merged_unit_whose_commit_is_on_the_default_branch_is_not_listed(
    scene: Scene,  # noqa: F811
) -> None:
    give_a_remote(scene.repo)
    commit_files(scene.repo, "unit work", {"unit.txt": "work\n"})
    git(scene.repo, "push", "-q", "origin", "main")
    scene.add(UNIT, MERGED, pr=2, merge_sha=git(scene.repo, "rev-parse", "HEAD").strip())

    found = checks(scene, FALSE_MERGES)

    assert found
    assert [c.status for c in found if c.status != "ok"] == []
    assert UNIT not in said(found)


def test_the_check_writes_nothing(scene: Scene) -> None:  # noqa: F811
    recorded_merged(scene, on_default=False)
    before = scene.snapshot()
    heads = git(scene.repo, "for-each-ref")

    found = checks(scene, FALSE_MERGES)

    assert UNIT in said(found)
    assert scene.snapshot() == before
    assert git(scene.repo, "for-each-ref") == heads
