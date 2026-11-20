"""`abk manual done` (spec: manual-steps): a person attests a step that declares no check.

The command runs through the real command line over a store in a temporary folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import PLANNED, ManualStep
from tests.conftest import make_installation
from tests.factories import stored_unit
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
        self.store.set_manual_steps(uid, steps)
        self.store.set_state(uid, PLANNED)

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
    attesting: Attesting,
) -> None:
    attesting.waiting("feature/1", bare())
    before = len(attesting.store.history("feature/1"))

    assert attesting.done(SLUG, "--note", NOTE) == 0

    step = attesting.step("feature/1")
    assert (step.done, step.outcome, step.last_line) == (True, "attested", NOTE)
    assert step.checked_at is not None
    added = attesting.store.history("feature/1")[before:]
    assert len(added) == 1
    assert SLUG in str(added[0]) and NOTE in str(added[0]) and added[0].get("by")


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
