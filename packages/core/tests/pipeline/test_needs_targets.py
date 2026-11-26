"""How a `Needs:` line is resolved against its target (spec: needs-targets)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import Member, UnitState
from tests.cli.replan_driver import tasks_md
from tests.factories import stored_unit, write_changes

NO_UNITS: tuple = ()


def write_change(changes: Path, folder: str, text: str | None) -> Path:
    if text is None:
        (changes / folder).mkdir(parents=True, exist_ok=True)
        (changes / folder / "proposal.md").write_text("# proposal\n")
    else:
        write_changes(changes, {folder: text})
    return changes / folder / "tasks.md"


def feature_needing(changes: Path, line: str) -> Path:
    return write_change(changes, "feature", tasks_md(1, needs={1: line}))


def joined_unit():
    return stored_unit(
        "other/1",
        change="other",
        groups=(1,),
        joined=(Member(change="base", groups=(1,)),),
    )


@pytest.mark.parametrize(
    ("target", "units", "archive", "outlines", "outcome"),
    [
        pytest.param(
            "base group 1",
            [stored_unit("base/1", change="base", groups=(1,))],
            None,
            (),
            None,
            id="a-planned-unit-carries-the-group",
        ),
        pytest.param("base group 1", "joined", None, (), None, id="a-joined-member-carries-it"),
        pytest.param(
            "base group 1",
            [stored_unit("base/1", change="base", groups=(1,), state=UnitState.RETIRED)],
            None,
            (),
            "not_planned",
            id="only-a-retired-unit-carries-it",
        ),
        pytest.param("done group 1", NO_UNITS, "done", (), None, id="an-archived-change-is-met"),
        pytest.param("base group 2", NO_UNITS, None, (), "not_planned", id="no-unit-for-group"),
        pytest.param("base group 9", NO_UNITS, None, (), "no_group", id="the-group-is-not-there"),
        pytest.param("draft group 1", NO_UNITS, None, (), "no_tasks", id="a-folder-without-tasks"),
        pytest.param("later group 1", NO_UNITS, None, ("later",), "outline", id="an-outline"),
        pytest.param("nothing group 1", NO_UNITS, None, (), "missing", id="no-such-name"),
        pytest.param(
            "upper-name group 1", NO_UNITS, None, (), "not_planned", id="names-match-any-case"
        ),
    ],
)
def test_a_needs_line_resolves_to_its_outcome(
    tmp_path: Path, target: str, units, archive: str | None, outlines: tuple, outcome: str | None
) -> None:
    from agent_build_kit.pipeline import needs_targets

    changes = tmp_path / "changes"
    changes.mkdir()
    if units == "joined":
        units = [joined_unit()]
    path = feature_needing(changes, target)
    write_change(changes, "base", tasks_md(2))
    write_change(changes, "Upper-Name", tasks_md(1))
    write_change(changes, "draft", None)
    if archive:
        (changes / "archive" / f"2026-11-01-{archive}").mkdir(parents=True)
        (changes / "archive" / f"2026-11-01-{archive}" / "tasks.md").write_text(tasks_md(1))
    active = [path, changes / "base" / "tasks.md"]

    unmet = needs_targets.unmet_needs(active, units, changes, outlines, {})

    assert [item.outcome for item in unmet if item.change == "feature"] == (
        [outcome] if outcome else []
    )


def test_an_unmet_line_carries_its_place_and_the_targets_plan_state(tmp_path: Path) -> None:
    from agent_build_kit.pipeline import needs_targets

    changes = tmp_path / "changes"
    path = feature_needing(changes, "base group 2")
    write_change(changes, "base", tasks_md(2))
    needs_line = next(
        number
        for number, text in enumerate(path.read_text().splitlines(), start=1)
        if text.startswith("Needs:")
    )

    unmet = needs_targets.unmet_needs(
        [path, changes / "base" / "tasks.md"],
        NO_UNITS,
        changes,
        (),
        {"base": "given up: group 2 is too large"},
    )

    [item] = [found for found in unmet if found.change == "feature"]
    assert (item.group, item.target, item.target_group) == (1, "base", 2)
    assert item.line == needs_line
    assert "given up: group 2 is too large" in item.wording
    assert "base group 2" in item.wording
