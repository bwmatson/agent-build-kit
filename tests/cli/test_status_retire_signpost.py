"""`abk status` lists the units to retire, each with the command to run (spec:
a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation, run_status
from tests.factories import stored_unit


def stored_installation(tmp_path: Path, units: list) -> Installation:
    """An installation whose store holds `units` exactly as given: a collision is stored
    as history left it, not as a plan could make it."""
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    UnitStore(tmp_path / "units.json").import_units(units)
    return inst


def retire_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if "abk retire" in line]


def orphan_and_its_builder() -> list:
    """`app/3` unplanned with a branch, and `app/4` merged, both carrying group 16."""
    return [
        stored_unit("app/3", state="unplanned", branch="spec/app/3", groups=(16,)),
        stored_unit("app/4", state="merged", branch="spec/app/4", pr=4, groups=(16,)),
    ]


def test_an_unplanned_unit_with_work_is_listed_with_the_command_and_nothing_is_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = run_status(stored_installation(tmp_path, orphan_and_its_builder()), monkeypatch, capsys)

    [line] = retire_lines(lines)
    assert 'abk retire app/3 --reason "..."' in line
    assert "nothing is lost: its groups are in app/4" in line


def test_an_unplanned_unit_whose_groups_nobody_built_says_nothing_of_the_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    orphan = stored_unit("app/3", state="unplanned", branch="spec/app/3", groups=(16,))

    lines = run_status(stored_installation(tmp_path, [orphan]), monkeypatch, capsys)

    [line] = retire_lines(lines)
    assert "abk retire app/3" in line
    assert "nothing is lost" not in "\n".join(lines)


def test_a_group_two_units_carry_is_listed_with_the_one_further_from_done_to_retire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [
        stored_unit("app/3", state="planned", branch="spec/app/3", groups=(8,)),
        stored_unit("app/5", state="in_review", branch="spec/app/5", pr=5, groups=(8,)),
    ]

    lines = run_status(stored_installation(tmp_path, units), monkeypatch, capsys)

    collision = [line for line in lines if "group 8" in line]
    assert collision, lines
    assert "app/3" in collision[0] and "app/5" in collision[0]
    assert "planned" in collision[0] and (
        "in_review" in collision[0] or "in review" in collision[0]
    )
    [suggestion] = retire_lines(lines)
    assert "abk retire app/3" in suggestion
    assert "suggest" in suggestion.lower()


def test_a_unit_retired_by_the_line_is_no_longer_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = stored_installation(tmp_path, orphan_and_its_builder())
    assert retire_lines(run_status(inst, monkeypatch, capsys))
    UnitStore(tmp_path / "units.json").retire("app/3", "built in app/4")

    lines = run_status(inst, monkeypatch, capsys)

    assert retire_lines(lines) == []
    assert not any("group 16" in line for line in lines)
