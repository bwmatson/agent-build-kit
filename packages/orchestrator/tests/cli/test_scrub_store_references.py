"""`abk scrub-store` counts and replaces issue and pull-request references beside the home paths
(spec: stored-text-scrub)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.scrub_store_support import (
    LINUX,
    UNIT,
    pause,
    planning_installation,
    run,
    seed,
    store_of,
)

REFERENCE = "<redacted>/app#15"
SCRUBBED = "<redacted>/<ref>"
COPY = "units.json.pre-redact"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    return planning_installation(tmp_path, monkeypatch)


def test_the_dry_run_counts_references_beside_home_paths_without_the_text(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed(inst, f"{LINUX} then {REFERENCE} failed")
    before = path.read_bytes()

    assert run(inst, "scrub-store") == 0

    out = capsys.readouterr()
    shown = out.out + out.err
    line = next(line for line in shown.splitlines() if UNIT in line and "feedback" in line)
    assert "2" in line
    assert "app#15" not in shown
    assert "someone" not in shown
    assert path.read_bytes() == before


def test_apply_rewrites_a_history_note_and_a_feedback_field_and_nothing_else(
    inst: Installation,
) -> None:
    seed(inst)
    store = store_of(inst)
    store.set_state(UNIT, IN_REVIEW, note=f"{REFERENCE} can't be closed")
    store.set_feedback(UNIT, f"{REFERENCE} failed")
    store.set_guidance(UNIT, "mind the base")
    pause(inst)

    assert run(inst, "scrub-store", "--apply") == 0

    unit = store_of(inst).get(UNIT)
    assert unit.feedback == f"{SCRUBBED} failed"
    assert unit.history[-1]["note"] == f"{SCRUBBED} can't be closed"
    assert unit.guidance == "mind the base"


def test_a_second_apply_finds_nothing_and_writes_nothing(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    path = seed(inst, f"{REFERENCE} failed")
    pause(inst)
    assert run(inst, "scrub-store", "--apply") == 0
    after_first = path.read_bytes()
    copy = (inst.state_dir / COPY).read_bytes()
    capsys.readouterr()

    assert run(inst, "scrub-store", "--apply") == 0

    assert "nothing found" in capsys.readouterr().out
    assert path.read_bytes() == after_first
    assert (inst.state_dir / COPY).read_bytes() == copy
