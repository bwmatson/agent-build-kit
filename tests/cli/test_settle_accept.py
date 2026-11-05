"""`abk settle <unit> --accept` ends the wait of a unit whose check will never finish (spec:
merged-waits-for-ci): a settling unit becomes merged with a note, any other unit is refused."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, SETTLING, UnitState
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation
from tests.factories import stored_unit


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    inst = make_installation(tmp_path / "planning")
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    return inst


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("add-marker/1")])
    return store


def test_accept_makes_a_settling_unit_merged_with_the_persons_reason_in_its_note(
    store: UnitStore,
) -> None:
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")

    code = main(["settle", "add-marker/1", "--accept", "--reason", "the runner was retired"])

    assert code == 0
    unit = store.get("add-marker/1")
    assert unit.state == MERGED
    assert "the runner was retired" in unit.history[-1]["note"]


@pytest.mark.parametrize("state", [IN_REVIEW, MERGED])
def test_accept_refuses_a_unit_that_is_not_settling(
    store: UnitStore, capsys: pytest.CaptureFixture[str], state: UnitState
) -> None:
    store.set_state("add-marker/1", state, pr=4, branch="spec/add-marker/1")

    code = main(["settle", "add-marker/1", "--accept"])

    assert code != 0
    assert store.get("add-marker/1").state == state
    assert "not settling" in capsys.readouterr().err


def test_accept_refuses_while_a_tick_holds_the_units_branch(
    inst: Installation, store: UnitStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tick running the failed check's tests on the base writes the unit's next state, and
    would undo an accept recorded meanwhile."""
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")

    with branch_lock("spec/add-marker/1", root=inst.locks_dir):
        code = main(["settle", "add-marker/1", "--accept"])

    assert code == 1
    assert store.get("add-marker/1").state == SETTLING
    assert "a tick is handling" in capsys.readouterr().err


def test_accept_succeeds_while_the_unit_s_late_check_waits_and_the_late_result_changes_nothing(
    inst: Installation, store: UnitStore
) -> None:
    """The late check waits for its unit-test slot without the unit's claim."""
    store.set_state("add-marker/1", SETTLING, pr=4, branch="spec/add-marker/1")
    waiting, release = threading.Event(), threading.Event()

    def waits_for_a_slot(unit: StoredUnit, logs: str) -> bool:
        waiting.set()
        release.wait(timeout=20)
        return False

    def late_check() -> None:
        events.on_late_check(
            4,
            repo="app",
            pull=PullRequest(
                number=4,
                head="spec/add-marker/1",
                base="main",
                state="merged",
                checks=(Check(name="test", status=CheckStatus.FAILED),),
            ),
            store=store,
            base_passes=waits_for_a_slot,
            claim=events.build_claim(inst.locks_dir),
            log=lambda message: None,
        )

    thread = threading.Thread(target=late_check, daemon=True)
    thread.start()
    try:
        assert waiting.wait(timeout=20)
        code = main(["settle", "add-marker/1", "--accept", "--reason", "known red base"])
    finally:
        release.set()
        thread.join(timeout=20)

    assert code == 0
    unit = store.get("add-marker/1")
    assert unit.state == MERGED
    assert "known red base" in unit.history[-1]["note"]
