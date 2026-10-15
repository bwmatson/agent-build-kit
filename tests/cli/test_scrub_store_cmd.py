"""`abk scrub-store`: a dry run that counts home paths in stored text, and `--apply`, which
replaces their prefix with `<home>/` on a paused pipeline (spec: stored-text-scrub)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from tests.scrub_store_support import (
    FEEDBACK,
    SCRUBBED,
    UNIT,
    pause,
    planning_installation,
    run,
    seed,
    store_of,
)

COPY = "units.json.pre-redact"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    return planning_installation(tmp_path, monkeypatch)


def shown_by(capsys: pytest.CaptureFixture[str]) -> str:
    out = capsys.readouterr()
    return out.out + out.err


def test_the_default_run_reports_record_field_and_count_without_text(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed(inst)
    before = path.read_bytes()

    assert run(inst, "scrub-store") == 0

    shown = shown_by(capsys)
    line = next(line for line in shown.splitlines() if UNIT in line)
    assert "feedback" in line
    assert "3" in line
    assert "someone" not in shown
    assert "work/app" not in shown
    assert path.read_bytes() == before
    assert not list(inst.state_dir.glob("*.pre-redact"))


def test_apply_replaces_each_home_prefix_and_keeps_the_original(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed(inst)
    original = path.read_bytes()
    pause(inst)

    assert run(inst, "scrub-store", "--apply") == 0

    assert store_of(inst).get(UNIT).feedback == SCRUBBED
    assert (inst.state_dir / COPY).read_bytes() == original
    assert "someone" not in shown_by(capsys)


def test_apply_without_a_pause_exits_1_names_the_pause_and_changes_nothing(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed(inst)
    before = path.read_bytes()

    assert run(inst, "scrub-store", "--apply") == 1

    assert "pause" in shown_by(capsys)
    assert path.read_bytes() == before
    assert not (inst.state_dir / COPY).exists()


def test_a_repo_name_in_feedback_is_kept(inst: Installation) -> None:
    seed(inst, FEEDBACK + " and repo app of platform")
    pause(inst)

    assert run(inst, "scrub-store", "--apply") == 0

    assert store_of(inst).get(UNIT).feedback == SCRUBBED + " and repo app of platform"
