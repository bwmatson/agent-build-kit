"""`abk review-plan show` and `clear`, and the held change in `abk status` (spec: plan-review).

A tick with a fake model leaves the findings; the commands run through the real command line.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from tests.plan_review_support import CHANGE, FINDING, Review, reply

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Review:
    run = Review(tmp_path, monkeypatch)
    run.runtime.answer = reply(FINDING)
    assert run.tick() == 0
    return run


def assert_held(run: Review) -> None:
    assert run.builder.started == [], "the finding holds the change: no unit started"


def command(run: Review, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    capsys.readouterr()
    code = main(["--config", str(run.config), "review-plan", *argv])
    seen = capsys.readouterr()
    return code, seen.out + seen.err


def test_show_prints_each_finding_with_its_group_question_and_evidence(
    held: Review, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_held(held)

    code, out = command(held, capsys, "show", CHANGE)

    assert code == 0
    assert "group 2" in out
    assert "question 1" in out
    assert str(FINDING["evidence"]) in out


def test_clear_records_the_note_and_the_next_tick_starts_the_first_unit(
    held: Review, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_held(held)

    code, _ = command(held, capsys, "clear", CHANGE, "--note", "accepted: the file is shared")

    assert code == 0
    _, shown = command(held, capsys, "show", CHANGE)
    assert "accepted: the file is shared" in shown, "the note is recorded with the review"
    assert held.tick() == 0
    assert held.builder.started, "the cleared change starts"
    assert held.asked == 1, "clearing asks for no new review"


def test_clearing_a_change_with_no_findings_says_so_and_exits_zero(
    held: Review, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_held(held)
    command(held, capsys, "clear", CHANGE)

    code, out = command(held, capsys, "clear", CHANGE)

    assert code == 0
    assert "no findings" in out


def test_status_shows_a_held_change_with_its_findings(
    held: Review, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_held(held)
    capsys.readouterr()

    assert cli.cmd_status(argparse.Namespace(), held.inst) == 0

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if CHANGE in line and "held" in line)
    assert "plan review" in line
    assert "group 2" in out
    assert str(FINDING["evidence"]) in out
