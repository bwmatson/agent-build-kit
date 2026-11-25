"""`abk status` lists a unit parked for its worktree with the reason, so a person
knows which tree to clean before requeueing it."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, SavedLeftovers, UnitStore
from agent_build_kit.pipeline.units import CLOSED, HELD, IN_REVIEW, MERGED, UnitState
from tests.conftest import make_installation
from tests.factories import stored_unit

REASON = "uncommitted changes in the worktree: stray.txt — commit or remove them by hand"


def test_status_lists_a_unit_parked_for_its_worktree_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("one/1", change="one"), stored_unit("two/1", change="two")])
    store.set_state("one/1", HELD, note=REASON, cause=Cause.DIRTY_WORKTREE)
    store.set_state("two/1", HELD, note="needs a human", cause=Cause.NEEDS_HUMAN)
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    parked = next(line for line in lines if "one/1" in line)
    assert "stray.txt" in parked
    assert "commit or remove" in parked
    assert not any("two/1" in line for line in lines), "other holds are not listed here"


def status_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    saves: dict[str, list[SavedLeftovers]],
    *,
    states: dict[str, UnitState] | None = None,
) -> list[str]:
    """What `abk status` prints for units that were each given the listed saves and put in their
    state from `states` (in review when not listed)."""
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(uid, change=uid.partition("/")[0]) for uid in saves])
    for uid, saved in saves.items():
        store.set_state(uid, (states or {}).get(uid, IN_REVIEW))
        for each in saved:
            store.record_leftovers(uid, each)
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), workspace) == 0
    return capsys.readouterr().out.splitlines()


def only_saved_line(lines: list[str]) -> str:
    """The one `leftovers saved` line of the output; an assertion fails when there is not one."""
    found = [each for each in lines if "leftovers saved" in each]
    assert len(found) == 1, lines
    return found[0]


def test_status_names_the_ref_the_files_and_the_command_for_a_running_unit_with_saved_leftovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ref = "refs/abk/leftovers/one/1"
    saved = SavedLeftovers(ref=ref, files=("stray.txt",), at="2026-11-24T00:00:00+00:00")

    lines = status_lines(tmp_path, monkeypatch, capsys, {"one/1": [saved]})

    line = only_saved_line(lines)
    assert "one/1" in line
    assert ref in line
    assert "stray.txt" in line
    assert f"git show --stat {ref}" in line


def test_status_names_each_ref_of_a_unit_with_two_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = SavedLeftovers(
        ref="refs/abk/leftovers/one/1", files=("a.txt",), at="2026-11-24T00:00:00+00:00"
    )
    second = SavedLeftovers(
        ref="refs/abk/leftovers/one/2", files=("b.txt",), at="2026-11-24T01:00:00+00:00"
    )

    lines = status_lines(tmp_path, monkeypatch, capsys, {"one/1": [first, second]})

    text = "\n".join(each for each in lines if "leftovers saved" in each)
    assert "refs/abk/leftovers/one/1" in text
    assert "refs/abk/leftovers/one/2" in text
    assert "a.txt" in text
    assert "b.txt" in text


def test_status_cuts_more_than_five_files_to_five_and_a_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    files = tuple(f"f{n}.txt" for n in range(8))
    saved = SavedLeftovers(
        ref="refs/abk/leftovers/one/1", files=files, at="2026-11-24T00:00:00+00:00"
    )

    lines = status_lines(tmp_path, monkeypatch, capsys, {"one/1": [saved]})

    line = only_saved_line(lines)
    assert all(name in line for name in files[:5])
    assert not any(name in line for name in files[5:])
    assert "and 3 more" in line


@pytest.mark.parametrize("state", [MERGED, CLOSED])
def test_status_prints_no_saved_leftovers_line_for_a_merged_or_closed_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: UnitState,
) -> None:
    saved = SavedLeftovers(
        ref="refs/abk/leftovers/one/1", files=("stray.txt",), at="2026-11-24T00:00:00+00:00"
    )

    running = SavedLeftovers(
        ref="refs/abk/leftovers/two/1", files=("kept.txt",), at="2026-11-24T00:00:00+00:00"
    )

    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        {"one/1": [saved], "two/1": [running]},
        states={"one/1": state},
    )

    assert "refs/abk/leftovers/two/1" in only_saved_line(lines), "the running unit's line"
    assert not any("refs/abk/leftovers/one/1" in each for each in lines)


def test_status_still_prints_the_parked_line_of_a_unit_held_for_its_worktree_that_has_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("one/1", change="one")])
    store.record_leftovers(
        "one/1",
        SavedLeftovers(
            ref="refs/abk/leftovers/one/1", files=("old.txt",), at="2026-11-24T00:00:00+00:00"
        ),
    )
    store.set_state("one/1", HELD, note=REASON, cause=Cause.DIRTY_WORKTREE)
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any("parked" in each and "stray.txt" in each for each in lines)
    assert "old.txt" in only_saved_line(lines)
