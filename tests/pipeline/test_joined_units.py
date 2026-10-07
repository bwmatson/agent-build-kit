"""A unit that carries task groups from more than one change.

A unit keeps one identity — its first change's id, branch and pull request —
and records the groups it has taken from other changes. Everything that used
to read "the unit's change and groups" reads its members instead. These tests
build a joined unit by hand: nothing here produces one by planning.
"""

import subprocess
from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.archive import archive_ready_changes, is_ready_to_archive
from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Member, UnitState, branch_name
from agent_build_kit.pipeline.verify import Verification, VerifyRecord, verify_change
from tests.conftest import make_installation
from tests.factories import stored_unit, unit

CARRIED = Member(change="sample-change", groups=(7, 8))


def carrying(uid: str = "add-marker/1", **overrides) -> StoredUnit:
    """A unit of add-marker that also carries groups 7 and 8 of sample-change."""
    return stored_unit(uid, joined=(CARRIED,), **overrides)


# --- 1.1 the model ---------------------------------------------------------


def test_a_unit_recorded_without_carried_groups_loads_and_is_its_own_member() -> None:
    """A store written before this change has no `joined` key at all."""
    loaded = StoredUnit.model_validate(
        {
            "id": "add-marker/1",
            "change": "add-marker",
            "title": "Register the marker",
            "repo": "app",
            "tier": "tier1",
            "groups": [1, 2],
        }
    )

    assert loaded.joined == ()
    assert loaded.members() == (Member(change="add-marker", groups=(1, 2)),)


def test_carried_groups_follow_the_units_own_in_order() -> None:
    second = Member(change="other-change", groups=(3,))
    joined = unit(groups=(1, 2), joined=(CARRIED, second))

    assert joined.members() == (
        Member(change="add-marker", groups=(1, 2)),
        CARRIED,
        second,
    )


def test_carrying_groups_does_not_change_the_units_identity() -> None:
    plain, joined = unit(), carrying()

    assert joined.id == plain.id
    assert branch_name(joined) == branch_name(plain)


def test_carried_groups_survive_the_store(tmp_path: Path) -> None:
    path = tmp_path / "units.json"
    UnitStore(path).upsert([carrying()])

    assert UnitStore(path).get("add-marker/1").joined == (CARRIED,)


# --- 1.2 prompts -----------------------------------------------------------


# --- 1.3 ticking -----------------------------------------------------------


def _tasks(tmp_path: Path, change: str, groups: tuple[int, ...]) -> Path:
    path = tmp_path / "meta" / "openspec" / "changes" / change / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            f"## {g}. [app] [tier1] G{g}\n- [ ] {g}.1 Test: a\n- [ ] {g}.2 Do a\n" for g in groups
        )
    )
    return path


def _ticked(tasks: Path) -> set[int]:
    return {
        int(line.split()[2].split(".")[0])
        for line in tasks.read_text().splitlines()
        if line.startswith("- [x]")
    }


# --- 1.4 archive readiness -------------------------------------------------


def test_a_change_wholly_carried_elsewhere_waits_for_that_unit_to_merge() -> None:
    carrier = stored_unit(
        "add-marker/1",
        joined=(Member(change="sample-change", groups=(1,)),),
        state="in_review",
    )

    assert not is_ready_to_archive("sample-change", [carrier])


def test_a_change_wholly_carried_elsewhere_is_ready_once_that_unit_has_merged() -> None:
    carrier = stored_unit(
        "add-marker/1",
        joined=(Member(change="sample-change", groups=(1,)),),
        state="merged",
    )

    assert is_ready_to_archive("sample-change", [carrier])


def test_a_change_with_one_group_carried_and_one_of_its_own_needs_both() -> None:
    own = stored_unit("sample-change/1", change="sample-change", groups=(1,), state="merged")
    carrier = stored_unit(
        "add-marker/1",
        joined=(Member(change="sample-change", groups=(2,)),),
        state="in_review",
    )

    assert not is_ready_to_archive("sample-change", [own, carrier])

    carrier = carrier.model_copy(update={"state": "merged"})

    assert is_ready_to_archive("sample-change", [own, carrier])


def _merged_carrier() -> StoredUnit:
    return stored_unit(
        "add-marker/1",
        joined=(Member(change="sample-change", groups=(1,)),),
        state="merged",
        pr=5,
    )


def test_a_change_wholly_carried_elsewhere_is_archived_by_the_tick(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    archived = archive_ready_changes([_merged_carrier()], planning_repo=tmp_path, run=run)

    assert sorted(archived) == ["add-marker", "sample-change"]
    assert any("sample-change" in call for call in calls)


def test_a_change_wholly_carried_elsewhere_is_listed_for_verification(tmp_path: Path) -> None:
    inst = make_installation(tmp_path)
    verified: list[str] = []

    def verify(change, units):
        verified.append(change)
        return Verification(change=change, passed=True, units=[])

    cli.verify_ready(inst, [_merged_carrier()], verify=verify)

    assert "sample-change" in verified


def test_verifying_a_carried_change_includes_the_carrying_units_files(tmp_path: Path) -> None:
    inst = make_installation(tmp_path)
    asked: list[tuple[str, int]] = []

    def pr_files(repo: str, pr: int) -> list[str]:
        asked.append((repo, pr))
        return ["README.md"]

    result = verify_change(
        "sample-change",
        [_merged_carrier()],
        installation=inst,
        pr_files=pr_files,
        run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""),
        env={},
    )

    assert asked == [("app", 5)]
    assert result.units == ["add-marker/1"]


def test_a_satisfied_carrier_keeps_ticks_busy_for_a_carried_change_waiting(
    tmp_path: Path,
) -> None:
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("add-marker/1", state="merged", pr=1),
            stored_unit("add-marker/2", groups=(2,), joined=(CARRIED,), state="satisfied"),
            stored_unit(
                "sample-change/1", change="sample-change", groups=(1,), state="merged", pr=2
            ),
        ]
    )

    # `upsert` keeps no PR; a merged unit carries one once it has been merged.
    store.set_state("add-marker/1", UnitState.MERGED, pr=1)
    store.set_state("sample-change/1", UnitState.MERGED, pr=2)
    # The carrier's own change is already verified, so only the carried one waits.
    VerifyRecord(inst.state_dir / "verified.json").put(
        Verification(change="add-marker", passed=True, units=["add-marker/1"])
    )

    assert cli.has_work(inst, store)


# --- 1.5 Needs -------------------------------------------------------------


def test_a_needs_line_naming_a_carried_group_resolves_to_the_carrying_unit(
    tmp_path: Path,
) -> None:
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    change = tmp_path / "openspec" / "changes" / "feature"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(
        "# Tasks\n\n## 6. [platform] [tier2] Reachable\n\n"
        "Needs: sample-change group 7 — the marker exists.\n\n"
        "- [ ] 6.1 Test: reachable\n"
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("add-marker/1", joined=(CARRIED,)),
            stored_unit("feature/1", change="feature", repo="platform", groups=(6,)),
        ]
    )

    cli.link_needs(inst, store=store)

    assert store.get("feature/1").depends_on == ("add-marker/1",)


def test_a_needs_line_on_a_carried_group_reaches_the_carrying_unit(tmp_path: Path) -> None:
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    change = tmp_path / "openspec" / "changes" / "sample-change"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(
        "# Tasks\n\n## 7. [app] [tier1] Carried\n\n"
        "Needs: feature group 6 — the platform side.\n\n"
        "- [ ] 7.1 Test: carried\n"
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("feature/1", change="feature", repo="platform", groups=(6,)),
            stored_unit("add-marker/1", joined=(CARRIED,)),
        ]
    )

    cli.link_needs(inst, store=store)

    assert store.get("add-marker/1").depends_on == ("feature/1",)


# --- 1.6 the pull request and the graph ------------------------------------


def test_the_pull_request_body_lists_each_change_with_its_groups() -> None:
    joined = carrying(groups=(1, 2))

    body = build_pr_body(joined, graph=[joined], base="main")

    assert "openspec/changes/add-marker" in body
    assert "1, 2" in body
    assert "openspec/changes/sample-change" in body
    assert "7, 8" in body


def test_the_graph_names_every_change_a_unit_carries() -> None:
    diagram = render_mermaid([stored_unit("add-marker/1", joined=(CARRIED,))])

    node = next(line for line in diagram.splitlines() if "add-marker/1<br/>" in line)
    assert "sample-change" in node
    assert "7, 8" in node


def test_a_unit_carrying_nothing_is_drawn_as_it_was() -> None:
    diagram = render_mermaid([stored_unit("add-marker/1")])

    assert "sample-change" not in diagram
