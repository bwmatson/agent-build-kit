"""`abk units prune --unplanned`: the sweep of `unplanned` units on demand, with a dry run that
lists what would go and why each other unit stays (spec: unplanned-sweep)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.units_cmd import cmd_units_prune
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.trackers.board_support import write_change


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    made = make_installation(tmp_path, planning={"state_dir": "."})
    write_change(made.changes_dir, "x")
    return made


def tombstones(inst: Installation, *extra: StoredUnit) -> UnitStore:
    """x/3 carried group 3 and was demoted when x/4 took it (nothing else names it), and x/5 is a
    tombstone with work that nothing replaced."""
    store = cli.store_for(inst)
    store.upsert([stored_unit("x/3", change="x", groups=(3,)), *extra])
    store.upsert([stored_unit("x/4", change="x", groups=(3,))], change="x")
    store.import_units(
        [
            *store.all(),
            stored_unit(
                "x/5", change="x", groups=(5,), state=UnitState.UNPLANNED, branch="spec/x/5"
            ),
        ]
    )
    return store


def prune(inst: Installation, *, dry_run: bool) -> int:
    return cmd_units_prune(argparse.Namespace(unplanned=True, dry_run=dry_run), inst)


def ids(store: UnitStore) -> set[str]:
    return {unit.id for unit in store.all()}


def test_a_dry_run_lists_what_it_would_remove_and_why_the_rest_stay(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tombstones(inst)
    before = store.path.read_text()

    assert prune(inst, dry_run=True) == 0

    out = capsys.readouterr().out
    assert "would remove x/3" in out
    assert "kept x/5" in out and "holds work" in out
    assert store.path.read_text() == before


def test_a_run_removes_the_eligible_units_and_lists_the_rest_with_their_reasons(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tombstones(inst)

    assert prune(inst, dry_run=False) == 0

    out = capsys.readouterr().out
    assert "removed x/3" in out
    assert "kept x/5" in out and "holds work" in out
    assert ids(store) == {"x/4", "x/5"}


def test_a_reference_is_repointed_and_said(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tombstones(inst, stored_unit("y/1", change="y", depends_on=("x/3",)))
    write_change(inst.changes_dir, "y")

    prune(inst, dry_run=False)

    assert store.get("y/1").depends_on == ("x/4",)
    assert "y/1" in capsys.readouterr().out


def test_nothing_unplanned_says_so(inst: Installation, capsys: pytest.CaptureFixture[str]) -> None:
    cli.store_for(inst).upsert([stored_unit("x/1", change="x", groups=(1,))])

    assert prune(inst, dry_run=True) == 0

    assert "no unplanned units" in capsys.readouterr().out


def test_a_missing_changes_folder_refuses_and_removes_nothing(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tombstones(inst)
    for path in sorted(inst.changes_dir.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    inst.changes_dir.rmdir()

    assert prune(inst, dry_run=False) == 1

    assert "x/3" in ids(store)


def test_the_flag_is_required() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["units", "prune"])
    parsed = parser.parse_args(["units", "prune", "--unplanned", "--dry-run"])
    assert parsed.unplanned and parsed.dry_run
