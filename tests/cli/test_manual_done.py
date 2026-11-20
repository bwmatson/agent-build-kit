"""`abk manual done` (spec: manual-steps): a person attests a step that declares no check.

The command runs through the real command line over a store in a temporary folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main, manual_cmd
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.manual_cmd import ATTESTED_BY
from agent_build_kit.config import dump
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED, ManualStep
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import install
from tests.parked_split_support import stub_round

SLUG = "migrate-dev-database"
NOTE = "ran 0003, list saved in the PR"


class Attesting:
    def __init__(self, tmp_path: Path) -> None:
        self.inst = make_installation(tmp_path / "planning")
        self.config = self.inst.root / "abk.yaml"
        self.config.write_text(dump(self.inst.config))
        self.store = UnitStore(self.inst.state_dir / "units.json")

    def waiting(self, uid: str, *steps: ManualStep) -> None:
        self.store.upsert([stored_unit(uid, change=uid.split("/")[0])])
        """`uid` as a run leaves it after stopping at `steps`: planned and parked on them."""
        self.store.set_manual_steps(uid, steps)
        self.store.record_step(uid, "open_pr")
        self.store.set_state(uid, PLANNED, cause=Cause.MANUAL_STEP)

    def done(self, *args: str) -> int:
        return main(["--config", str(self.config), "manual", "done", *args])

    def step(self, uid: str, slug: str = SLUG) -> ManualStep:
        return next(s for s in self.store.get(uid).manual_steps if s.slug == slug)


@pytest.fixture
def attesting(tmp_path: Path) -> Attesting:
    return Attesting(tmp_path)


def bare(slug: str = SLUG) -> ManualStep:
    return ManualStep(slug=slug, text=f"A person does {slug}")


def test_attesting_marks_the_step_done_with_the_note_and_the_time_and_names_who(
    attesting: Attesting, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = install(monkeypatch)
    monkeypatch.setattr(manual_cmd, "current_user", lambda: "alice")
    attesting.waiting("feature/1", bare())
    before = len(attesting.store.history("feature/1"))

    assert attesting.done(SLUG, "--note", NOTE) == 0

    step = attesting.step("feature/1")
    assert (step.done, step.outcome, step.last_line) == (True, "attested", NOTE)
    assert (step.checked_at, step.attested_by) == (clock.now(), "alice")
    added = attesting.store.history("feature/1")[before:]
    assert len(added) == 1
    assert SLUG in str(added[0]) and NOTE in str(added[0]) and "alice" in str(added[0])
    assert added[0].get("by") == ATTESTED_BY


def test_attesting_a_step_on_a_planned_unit_with_no_cause_leaves_the_cause_none(
    attesting: Attesting,
) -> None:
    attesting.store.upsert([stored_unit("feature/1", change="feature")])
    attesting.store.set_manual_steps("feature/1", (bare(),))
    attesting.store.set_state("feature/1", PLANNED)

    assert attesting.done(SLUG) == 0

    assert attesting.store.get("feature/1").cause is None


def test_a_tick_pass_after_attesting_resumes_the_unit_with_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scripted_engine: None
) -> None:
    stub_round(monkeypatch)
    attesting = Attesting(tmp_path)
    attesting.waiting("feature/1", bare())
    attesting.done(SLUG, "--note", NOTE)

    cli.run_round(attesting.inst, attesting.store, building=(), only=frozenset(), submit=False)

    stored = attesting.store.get("feature/1")
    assert stored.history[-1]["note"] == f"requeued: manual step {SLUG} done"


def test_a_step_that_declares_a_check_is_refused_naming_abk_manual_check(
    attesting: Attesting, capsys: pytest.CaptureFixture[str]
) -> None:
    attesting.waiting("feature/1", ManualStep(slug=SLUG, text="A person", check="test -f x"))
    before = attesting.store.get("feature/1")

    code = attesting.done(SLUG)

    assert code != 0
    assert f"abk manual check {SLUG}" in capsys.readouterr().err
    assert attesting.store.get("feature/1") == before


def test_an_unknown_slug_is_refused_and_changes_nothing(
    attesting: Attesting, capsys: pytest.CaptureFixture[str]
) -> None:
    attesting.waiting("feature/1", bare())
    before = attesting.store.get("feature/1")

    code = attesting.done("no-such-step")

    assert code != 0
    assert "no-such-step" in capsys.readouterr().err
    assert attesting.store.get("feature/1") == before


def test_a_slug_on_two_waiting_units_is_refused_naming_both_unless_unit_picks_one(
    attesting: Attesting, capsys: pytest.CaptureFixture[str]
) -> None:
    attesting.waiting("feature/1", bare())
    attesting.waiting("platform/2", bare())

    code = attesting.done(SLUG)

    err = capsys.readouterr().err
    assert code != 0 and "feature/1" in err and "platform/2" in err
    assert not attesting.step("feature/1").done and not attesting.step("platform/2").done
    assert attesting.done(SLUG, "--unit", "platform/2") == 0
    assert attesting.step("platform/2").done and not attesting.step("feature/1").done


def test_a_step_already_done_is_reported_and_nothing_changes(
    attesting: Attesting, capsys: pytest.CaptureFixture[str]
) -> None:
    attesting.waiting("feature/1", bare())
    attesting.done(SLUG, "--note", NOTE)
    before = attesting.store.get("feature/1")
    capsys.readouterr()

    attesting.done(SLUG, "--note", "again")

    assert "already done" in capsys.readouterr().out.lower()
    assert attesting.store.get("feature/1") == before
