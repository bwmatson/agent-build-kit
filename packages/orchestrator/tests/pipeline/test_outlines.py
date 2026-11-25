"""Outlines: the distance of each, which are ready to detail, and the overlaps with detailed
changes (spec: outlines-are-detailed-one-unit-ahead)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.outlines import overlaps, read_outlines, readings, ready_outlines
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Member, UnitState
from tests.conftest import make_installation
from tests.factories import stored_unit


def planning(tmp_path: Path, lead: int = 1) -> Installation:
    return make_installation(tmp_path, planning=dict(state_dir=".", outline_lead_units=lead))


def write_outline(
    inst: Installation,
    name: str,
    *,
    waits: tuple[str, ...] = (),
    touches: str = "",
    reworks: tuple[str, ...] = (),
    groups: int = 1,
    extra: str = "",
) -> None:
    folder = inst.root / inst.config.planning.outlines / name
    folder.mkdir(parents=True)
    sketch = "\n".join(f"{n}. [app] [unit-test] Part {n}" for n in range(1, groups + 1))
    lines = [
        f"# {name}",
        "",
        f"Initiative: grow — wave 1: {name}",
        "",
        "## Its part",
        f"What {name} does.",
        "",
        "## Groups (sketch)",
        sketch,
        "",
        *waits,
        *([f"Touches: {touches}"] if touches else []),
        *reworks,
        extra,
    ]
    (folder / "proposal.md").write_text("\n".join(lines) + "\n")


def write_change(inst: Installation, name: str, tasks: str = "") -> None:
    folder = inst.changes_dir / name
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text(f"# {name}\n\n## 1. [app] [unit-test] Work\n\n{tasks}\n")


def waits(target: str, group: int) -> str:
    return f"Waits on: {target} group {group} — it must land first"


def unit(uid: str, state: UnitState, *depends: str, group: int | None = None, **more) -> StoredUnit:
    change, _, number = uid.partition("/")
    return stored_unit(
        uid,
        change=change,
        groups=(group or int(number),),
        state=state,
        depends_on=depends,
        **more,
    )


def distance_of(inst: Installation, units: list[StoredUnit], name: str = "next") -> int | None:
    return next(r.distance for r in readings(inst, units) if r.outline.name == name)


R, P, REVIEW, H, F = (
    UnitState.RUNNING,
    UnitState.PLANNED,
    UnitState.IN_REVIEW,
    UnitState.HELD,
    UnitState.FAILED,
)
NOTHING_AHEAD = (
    UnitState.SETTLING,
    UnitState.SATISFIED,
    UnitState.CLOSED,
    UnitState.RETIRED,
    UnitState.UNPLANNED,
)

DISTANCES = {
    "no waits line": ([], [], 0),
    "running parent and planned child": (
        [waits("base", 2)],
        [unit("base/1", R), unit("base/2", P, "base/1")],
        2,
    ),
    "parent in review": (
        [waits("base", 2)],
        [unit("base/1", REVIEW), unit("base/2", P, "base/1")],
        1,
    ),
    "both merged": (
        [waits("base", 2)],
        [unit("base/1", UnitState.MERGED), unit("base/2", UnitState.MERGED, "base/1")],
        0,
    ),
    "a held unit ahead counts": ([waits("base", 1)], [unit("base/1", H)], 1),
    "a failed unit ahead counts": ([waits("base", 1)], [unit("base/1", F)], 1),
    **{
        f"a {state.value} unit counts nothing": ([waits("base", 1)], [unit("base/1", state)], 0)
        for state in NOTHING_AHEAD
    },
    "a joined member carrying the group counts": (
        [waits("base", 2)],
        [unit("other/1", R, joined=(Member(change="base", groups=(2,)),))],
        1,
    ),
    "an unrelated running unit counts nothing": (
        [waits("base", 1)],
        [unit("base/1", UnitState.MERGED), unit("elsewhere/1", R)],
        0,
    ),
    "an ancestor already in review counts nothing": (
        [waits("base", 2)],
        [unit("base/1", REVIEW), unit("base/2", REVIEW, "base/1")],
        0,
    ),
    "a detailed change with no unit counts each group up to the named one": (
        [waits("base", 2)],
        [],
        2,
    ),
    "two waits lines take the longer": (
        [waits("base", 1), waits("base", 3)],
        [unit("base/1", R), unit("base/2", P, "base/1"), unit("base/3", P, "base/2")],
        3,
    ),
}


@pytest.mark.parametrize(("waits_lines", "units", "expected"), DISTANCES.values(), ids=DISTANCES)
def test_the_distance_counts_the_units_ahead_that_are_not_yet_in_review(
    tmp_path: Path, waits_lines: list[str], units: list[StoredUnit], expected: int
) -> None:
    inst = planning(tmp_path)
    write_change(inst, "base")
    write_outline(inst, "next", waits=tuple(waits_lines))

    assert distance_of(inst, units) == expected


def test_an_outlined_prerequisite_adds_its_sketched_groups_to_its_own_distance(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_change(inst, "base")
    write_outline(inst, "next", waits=(waits("base", 1),), groups=3)
    write_outline(inst, "far", waits=(waits("next", 2),))

    far = next(r for r in readings(inst, [unit("base/1", R)]) if r.outline.name == "far")

    assert far.distance == 3
    assert ("next", 2, 3) in far.ahead


def test_a_name_that_is_neither_a_change_nor_an_outline_counts_nothing_and_is_not_found(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_outline(inst, "next", waits=(waits("archived", 1),))

    (reading,) = readings(inst, [])

    assert (reading.distance, reading.not_found) == (0, ("archived",))


def test_an_outline_is_parsed_whole_and_a_waits_line_without_a_group_is_reported(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_outline(
        inst,
        "next",
        waits=(waits("base", 2), "Waits on: base — no group given"),
        touches="`packages/core/**`, `docs/cli.md`",
        reworks=("Reworks: base — builds the stub this redoes", "Reworks: other — same"),
        groups=3,
    )
    (inst.root / inst.config.planning.outlines / "stale" / "draft").mkdir(parents=True)

    (outline,) = read_outlines(inst)

    assert outline.name == "next"
    assert outline.initiative == "grow — wave 1: next"
    assert "What next does." in outline.its_part
    assert outline.groups == (1, 2, 3)
    assert [(w.target, w.group) for w in outline.waits_on] == [("base", 2)]
    assert outline.touches == ("packages/core/**", "docs/cli.md")
    assert len(outline.reworks) == 2
    assert [line for line in outline.unparsed if "no group given" in line]


def test_outlines_waiting_on_each_other_are_on_a_cycle_with_no_distance_and_are_not_ready(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    write_outline(inst, "a", waits=(waits("b", 1),))
    write_outline(inst, "b", waits=(waits("a", 1),))
    write_outline(inst, "c", waits=(waits("a", 1),))

    found = {r.outline.name: r for r in readings(inst, [])}

    assert {name: r.distance for name, r in found.items()} == {"a": None, "b": None, "c": None}
    assert found["a"].cycle and found["b"].cycle and found["c"].cycle
    assert ready_outlines(inst, []) == []


@pytest.mark.parametrize(
    ("lead", "ready"), [(1, ["near", "now"]), (0, ["now"])], ids=["lead 1", "lead 0"]
)
def test_the_ready_outlines_are_those_within_the_lead(
    tmp_path: Path, lead: int, ready: list[str]
) -> None:
    inst = planning(tmp_path, lead)
    write_change(inst, "base")
    write_outline(inst, "now")
    write_outline(inst, "near", waits=(waits("base", 1),))
    write_outline(inst, "far", waits=(waits("base", 3),))

    found = ready_outlines(inst, [unit("base/1", R)])

    assert sorted(r.outline.name for r in found) == ready


OVERLAPS = {
    "a glob covers a named path": ("packages/core/**", 3, True),
    "the same path": ("packages/core/src/agent_build_kit/config.py", 1, False),
    "an unrelated glob": ("docs/**", 3, None),
}


@pytest.mark.parametrize(("touches", "reworks", "flag"), OVERLAPS.values(), ids=OVERLAPS)
def test_a_touches_path_overlapping_a_named_path_is_listed_with_its_reworks_count(
    tmp_path: Path, touches: str, reworks: int, flag: bool | None
) -> None:
    inst = planning(tmp_path)
    write_change(inst, "feature", "- [ ] 1.1 Edit `packages/core/src/agent_build_kit/config.py`.")
    write_outline(
        inst,
        "later",
        touches=f"`{touches}`",
        reworks=tuple(f"Reworks: feature — redo {n}" for n in range(reworks)),
    )

    found = overlaps(inst)

    if flag is None:
        assert found == []
    else:
        assert [(o.change, o.outline, o.reworks, o.promote_earlier) for o in found] == [
            ("feature", "later", reworks, flag)
        ]


def test_a_glob_a_change_names_overlaps_an_outline_path_it_matches(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_change(inst, "feature", "Paths: `packages/core/**`")
    write_outline(inst, "later", touches="`packages/core/src/agent_build_kit/config.py`")

    assert [(o.change, o.outline) for o in overlaps(inst)] == [("feature", "later")]


def test_a_paths_line_counts_and_an_outline_path_and_glob_both_overlap_it(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    write_change(inst, "feature", "Paths: `docs/cli.md`")
    write_outline(inst, "later", touches="`docs/cli.md`")
    write_outline(inst, "wide", touches="`docs/**`")

    assert sorted(o.outline for o in overlaps(inst)) == ["later", "wide"]
