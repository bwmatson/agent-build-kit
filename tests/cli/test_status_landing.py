"""`abk status` says why a unit in review was not landed (spec: auto-land).

The landing pass runs over a stand-in forge, and the status is read from what it left in the
installation, so the test does not depend on how the reason is stored."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation, run_status
from tests.factories import new_unit
from tests.landing_support import PR, UNIT, Landing, landing
from tests.verdict_fakes import write_verdicts


def unit_lines(landed: Landing, patch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    return [line for line in run_status(landed.inst, patch, capsys) if f"{UNIT} " in line]


def test_a_declined_unit_shows_the_reason_in_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    landed = landing(tmp_path, monkeypatch)
    landed.forge.on_pr[PR] = {HOLD_LABEL}
    landed.land()

    lines = unit_lines(landed, monkeypatch, capsys)

    assert any("held by label" in line for line in lines), "\n".join(lines)


def test_a_unit_declined_for_having_no_checks_shows_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    landed = landing(tmp_path, monkeypatch)
    landed.forge.prs[0] = landed.forge.prs[0].model_copy(update={"checks": ()})
    landed.land()

    lines = unit_lines(landed, monkeypatch, capsys)

    assert any("no checks" in line for line in lines), "\n".join(lines)


def test_a_unit_waiting_only_on_pending_checks_shows_no_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    landed = landing(tmp_path, monkeypatch)
    pending = (Check(name="build", status=CheckStatus.PENDING),)
    landed.forge.prs[0] = landed.forge.prs[0].model_copy(update={"checks": pending})
    held = landing(tmp_path / "held", monkeypatch)
    held.forge.on_pr[PR] = {HOLD_LABEL}
    held.land()
    landed.land()

    lines = unit_lines(landed, monkeypatch, capsys)

    assert lines, "the unit is still listed as waiting"
    assert not any("pending" in line or "not landed" in line for line in lines), "\n".join(lines)
    # The same status over a declined unit does show a reason, so the silence is the pending case.
    assert any("held by label" in line for line in unit_lines(held, monkeypatch, capsys))


def test_a_unit_the_landing_step_is_not_concerned_with_shows_no_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    landed = landing(tmp_path, monkeypatch)
    landed.forge.on_pr[PR] = {HOLD_LABEL}
    write_verdicts(landed.inst.state_dir / VERDICTS, {UNIT: ReviewTier.LIGHT}, unit_class="docs")
    landed.land()
    held = landing(tmp_path / "held", monkeypatch)
    held.forge.on_pr[PR] = {HOLD_LABEL}
    held.land()

    lines = unit_lines(landed, monkeypatch, capsys)

    assert lines
    assert not any("held by label" in line or "not landed" in line for line in lines)
    assert any("held by label" in line for line in unit_lines(held, monkeypatch, capsys))


def test_a_decline_ended_by_a_rework_is_no_longer_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    landed = landing(tmp_path, monkeypatch)
    landed.forge.on_pr[PR] = {HOLD_LABEL}
    landed.land()
    assert any("held by label" in line for line in unit_lines(landed, monkeypatch, capsys))

    landed.store.set_state(UNIT, IN_REVIEW, note="rework")
    write_verdicts(landed.inst.state_dir / VERDICTS, {UNIT: ReviewTier.LIGHT}, unit_class="docs")

    lines = unit_lines(landed, monkeypatch, capsys)

    assert lines
    assert not any("held by label" in line or "not landed" in line for line in lines)


PARENT = "feature/1"
DEPENDENT = "feature/2"
OFF_PR = 5
OFF_BRANCH = f"spec/{PARENT}"


@pytest.fixture
def held_installation(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )


def hold(inst: Installation, cause: Cause, note: str) -> None:
    """`feature/1` held with `cause`, and `feature/2` parked on it."""
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([new_unit(PARENT), new_unit(DEPENDENT, depends_on=(PARENT,))])
    store.set_state(PARENT, HELD, pr=OFF_PR, branch=OFF_BRANCH, note=note, cause=cause)
    store.set_state(DEPENDENT, PLANNED, note="parked", cause=Cause.GATED)
    store.set_needs(DEPENDENT, (PARENT,))


def test_status_shows_a_unit_landed_off_the_default_branch_and_what_a_person_can_do(
    held_installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hold(held_installation, Cause.LANDED_OFF_DEFAULT, f"#{OFF_PR} was merged into {OFF_BRANCH}")

    lines = run_status(held_installation, monkeypatch, capsys)

    shown_lines = [line for line in lines if f"{PARENT} " in line and "landed off" in line]
    assert len(shown_lines) == 1, "\n".join(lines)
    shown = shown_lines[0]
    assert "landed off the default branch" in shown
    assert f"#{OFF_PR}" in shown
    assert OFF_BRANCH in shown
    assert "carry" in shown, "it says what a person can do"


def test_status_says_a_dependent_waits_on_a_unit_landed_off_the_default_branch(
    held_installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hold(held_installation, Cause.LANDED_OFF_DEFAULT, f"#{OFF_PR} was merged into {OFF_BRANCH}")

    lines = run_status(held_installation, monkeypatch, capsys)

    waiting = [line for line in lines if f"{DEPENDENT} " in line]
    assert waiting
    assert any("landed off the default branch" in line for line in waiting), "\n".join(lines)


def test_status_shows_a_unit_whose_base_was_not_moved_and_what_a_person_can_do(
    held_installation: Installation,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hold(held_installation, Cause.BASE_NOT_MOVED, f"#{OFF_PR} could not be moved onto main")

    lines = run_status(held_installation, monkeypatch, capsys)

    shown_lines = [line for line in lines if f"{PARENT} " in line and "base not moved" in line]
    assert len(shown_lines) == 1, "\n".join(lines)
    shown = shown_lines[0]
    assert f"#{OFF_PR}" in shown
    assert "main" in shown
    assert "retarget" in shown, "it says what a person can do"


@pytest.mark.parametrize(
    ("cause", "words"),
    [
        (Cause.LANDED_OFF_DEFAULT, ("landed off the default branch", OFF_BRANCH, "carry")),
        (Cause.BASE_NOT_MOVED, ("base not moved", "main", "retarget")),
    ],
    ids=["landed-off-default", "base-not-moved"],
)
def test_explain_says_why_a_unit_is_held_for_these_causes(
    held_installation: Installation,
    capsys: pytest.CaptureFixture[str],
    cause: Cause,
    words: tuple[str, ...],
) -> None:
    hold(held_installation, cause, f"#{OFF_PR} on {OFF_BRANCH}, wanted main")
    capsys.readouterr()

    code = cmd_explain(argparse.Namespace(unit=PARENT, at=None), held_installation)

    out = capsys.readouterr().out
    assert code == 0
    assert f"#{OFF_PR}" in out
    for word in words:
        assert word in out, out
