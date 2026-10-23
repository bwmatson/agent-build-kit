"""`abk status` says why a unit in review was not landed (spec: auto-land).

The landing pass runs over a stand-in forge, and the status is read from what it left in the
installation, so the test does not depend on how the reason is stored."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import run_status
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
