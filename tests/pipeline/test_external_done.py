"""A hand merge is verified, then recorded on the held unit (spec: external-work)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.archive import is_ready_to_archive
from agent_build_kit.pipeline.external_done import HandMergeRefused, record_hand_merge
from agent_build_kit.pipeline.external_file import DONE, add_hold, read_holds
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.units import MERGED, PLANNED
from tests.external_support import hold, waits_of, world_of
from tests.factories import init_repo, stored_unit
from tests.forges.stand_in import StandInForge

MERGED_PR = 5
OPEN_PR = 6
COMMIT = "c" * 40


def forge_for(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> StandInForge:
    """A forge where pull request 5 is merged as `COMMIT` and 6 is open."""
    forge = StandInForge()
    forge.merged[MERGED_PR] = COMMIT
    monkeypatch.setattr(inst, "forge_of", lambda repo: (forge, forge.repo_id()))
    return forge


def checked(folder: Path) -> list[str]:
    """The numbers of the tasks ticked in the change's `tasks.md`."""
    lines = (folder / "tasks.md").read_text().splitlines()
    return [line.split()[2] for line in lines if line.startswith("- [x]")]


def held_world(tmp_path: Path, groups: tuple[int, ...] = (2, 3)):
    inst, store, folder = world_of(
        tmp_path, stored_unit("feature/1", change="feature", groups=groups)
    )
    add_hold(folder, hold(groups))
    return inst, store, folder


def test_a_merged_pull_request_marks_the_unit_merged_and_the_hold_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, folder = held_world(tmp_path)
    forge_for(inst, monkeypatch)

    record_hand_merge(inst, store, "feature", (2, 3), pr=MERGED_PR)

    unit = store.get("feature/1")
    assert unit.state == MERGED
    assert unit.merge_sha == COMMIT
    assert any("recorded by hand" in str(entry.get("note", "")) for entry in unit.history)
    assert checked(folder) == ["2.1", "3.1"]
    assert [h.status for h in read_holds(folder)] == [DONE]


def test_an_open_pull_request_is_refused_and_nothing_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, folder = held_world(tmp_path)
    forge_for(inst, monkeypatch)

    with pytest.raises(HandMergeRefused, match="not merged"):
        record_hand_merge(inst, store, "feature", (2, 3), pr=OPEN_PR)

    assert store.get("feature/1").state == PLANNED
    assert checked(folder) == []
    assert [h.status for h in read_holds(folder)] == ["held"]


def with_origin(inst: Installation, tmp_path: Path) -> tuple[Path, str]:
    """The `app` checkout as a repository on `main` with an origin; returns it and the commit
    at the tip of `main`."""
    checkout = init_repo(inst.repo("app").path)
    (checkout / "a.txt").write_text("a\n")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "work")
    remote = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    git(checkout, "remote", "add", "origin", str(remote))
    git(checkout, "push", "-q", "origin", "main")
    return checkout, git(checkout, "rev-parse", "HEAD").stdout.strip()


def test_a_commit_on_the_default_branch_is_accepted(tmp_path: Path) -> None:
    inst, store, folder = held_world(tmp_path)
    _checkout, tip = with_origin(inst, tmp_path)

    record_hand_merge(inst, store, "feature", (2, 3), commit=tip)

    unit = store.get("feature/1")
    assert (unit.state, unit.merge_sha) == (MERGED, tip)
    assert checked(folder) == ["2.1", "3.1"]


def test_a_commit_on_a_side_branch_is_refused(tmp_path: Path) -> None:
    inst, store, folder = held_world(tmp_path)
    checkout, _tip = with_origin(inst, tmp_path)
    git(checkout, "checkout", "-q", "-b", "side")
    (checkout / "b.txt").write_text("b\n")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-q", "-m", "side work")
    side = git(checkout, "rev-parse", "HEAD").stdout.strip()
    git(checkout, "push", "-q", "origin", "side")

    with pytest.raises(HandMergeRefused, match="default branch"):
        record_hand_merge(inst, store, "feature", (2, 3), commit=side)

    assert store.get("feature/1").state == PLANNED
    assert checked(folder) == []


def test_a_unit_is_merged_only_when_all_its_groups_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, folder = held_world(tmp_path)
    forge_for(inst, monkeypatch)

    record_hand_merge(inst, store, "feature", (2,), pr=MERGED_PR)

    assert checked(folder) == ["2.1"]
    assert store.get("feature/1").state == PLANNED
    assert waits_of(inst, store)["feature/1"].reason.value == "external"

    record_hand_merge(inst, store, "feature", (3,), pr=MERGED_PR)

    assert checked(folder) == ["2.1", "3.1"]
    assert store.get("feature/1").state == MERGED


def test_the_pull_request_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inst, store, _folder = held_world(tmp_path)
    forge = forge_for(inst, monkeypatch)

    record_hand_merge(inst, store, "feature", (2, 3), pr=MERGED_PR)

    assert forge.calls == []
    assert forge.added == []
    assert forge.comments == []


def test_a_change_whose_units_are_all_merged_by_hand_is_ready_to_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store, _folder = held_world(tmp_path, groups=(1,))
    forge_for(inst, monkeypatch)
    assert not is_ready_to_archive("feature", store.all())

    record_hand_merge(inst, store, "feature", (1,), pr=MERGED_PR)

    assert is_ready_to_archive("feature", store.all())
