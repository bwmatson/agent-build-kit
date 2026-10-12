"""`abk requeue --note` and `--note-file` hand a person's words to the unit's next run.

A note needs the agent to run, so it goes with `--rework` or `--restart`; a plain requeue
resumes a step that would not read it, and is refused. Without a thread to deliver to, the
requeue is made on the store, as it is for any unit whose build has no saved place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.conftest import make_installation
from tests.factories import stored_unit, unit

UNIT = "add-marker/1"
NOTE = "give the date as printed; " * 12  # longer than the 200 characters a history entry holds


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> UnitStore:
    inst = make_installation(tmp_path / "planning")
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([unit(UNIT)])
    store.set_state(UNIT, UnitState.FAILED, branch=f"spec/{UNIT}")
    store.set_feedback(UNIT, "a saved failure")
    return store


@pytest.mark.parametrize("mode", ["--rework", "--restart"])
def test_a_note_is_recorded_and_its_first_200_characters_are_in_the_history(
    store: UnitStore, mode: str
) -> None:
    assert main(["requeue", UNIT, mode, "--note", NOTE]) == 0

    after = store.get(UNIT)
    assert after.state == "planned"
    assert after.guidance == NOTE
    entry = after.history[-1]["note"]
    assert NOTE[:200] in entry
    assert NOTE[:201] not in entry


@pytest.mark.parametrize("mode", ["--rework", "--restart"])
def test_a_note_file_is_read_as_the_note(store: UnitStore, tmp_path: Path, mode: str) -> None:
    path = tmp_path / "note.txt"
    path.write_text(NOTE)

    assert main(["requeue", UNIT, mode, "--note-file", str(path)]) == 0

    after = store.get(UNIT)
    assert after.guidance == NOTE
    assert NOTE[:200] in after.history[-1]["note"]


def test_a_restart_clears_the_failure_and_keeps_the_note(store: UnitStore) -> None:
    assert main(["requeue", UNIT, "--restart", "--note", "start from the date"]) == 0

    after = store.get(UNIT)
    assert after.feedback == ""
    assert after.guidance == "start from the date"


def test_a_held_unit_with_no_saved_failure_is_reworked_only_with_a_note(
    store: UnitStore, capsys: pytest.CaptureFixture[str]
) -> None:
    store.set_state(UNIT, UnitState.HELD)
    store.set_feedback(UNIT, "")

    assert main(["requeue", UNIT, "--rework"]) == 1
    assert store.get(UNIT).state == "held"
    assert "no saved failure" in capsys.readouterr().out

    assert main(["requeue", UNIT, "--rework", "--note", "reword the title"]) == 0

    after = store.get(UNIT)
    assert after.state == "planned"
    assert after.guidance == "reword the title"


def test_a_note_with_a_plain_requeue_is_refused_and_changes_nothing(
    store: UnitStore, capsys: pytest.CaptureFixture[str]
) -> None:
    before = store.get(UNIT)

    try:
        code = main(["requeue", UNIT, "--note", "reword the title"])
    except SystemExit as stopped:
        code = int(stopped.code or 0)

    shown = capsys.readouterr()
    said = shown.out + shown.err
    assert code != 0
    assert "--rework" in said and "--restart" in said
    assert store.get(UNIT) == before


def test_a_thread_is_delivered_the_note_with_the_requeue(
    store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    delivered: list[dict[str, Any]] = []

    def resume_thread(inst: Any, subject: Any, kind: str, **kwargs: Any) -> None:
        delivered.append(kwargs)

    monkeypatch.setattr(cli, "resume_thread", resume_thread)

    assert main(["requeue", UNIT, "--rework", "--note", "reword the title"]) == 0

    [call] = delivered
    assert call["guidance"] == "reword the title"


def test_a_gated_requeue_keeps_the_note_while_it_waits(
    store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.upsert([stored_unit("dep/1", change="dep", repo="platform")])
    store.set_state("dep/1", UnitState.IN_REVIEW, pr=3)
    store.set_dependencies(UNIT, ("dep/1",))
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)

    assert main(["requeue", UNIT, "--rework", "--note", "reword the title"]) == 0

    held = store.get(UNIT)
    assert (held.state, held.cause) == ("planned", Cause.GATED)
    assert held.gated_requeue is RequeueReason.FROM_FAILURE
    assert held.guidance == "reword the title"
