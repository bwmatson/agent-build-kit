"""The recorded verdict changes nothing the pipeline does (spec: review-verdict)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.ecosystem_names import SOURCE_ROOT
from tests.factories import activate_with
from tests.graph.test_build_path import build, fresh

UNIT_ID = "add-marker/1"
# The recording module, the review node that writes through it, the status listing, and the
# review labels, the ordering of what is shown, the web server's review answer and pipeline
# summary (spec: review-triage allows each to read a verdict), and the report of the rates and
# gates (spec: review-outcomes), and the usage forecast's history of a tier, which is by the
# tier planned in the verdict record (spec: usage-pause).
ALLOWED = {
    "pipeline/verdict_record.py",
    "graph/nodes.py",
    "cli/pipeline.py",
    "pipeline/labels.py",
    "pipeline/review_order.py",
    "serve/server.py",
    "cli/review_report.py",
    "pipeline/landing.py",  # the landing pass reads the recorded final verdict
    "pipeline/usage_forecast_history.py",
    "pipeline/usage_forecast_unit.py",
}
NAMES = re.compile(r"verdicts\.json|verdict_record|\bVERDICTS\b")


@pytest.fixture
def review_enabled() -> None:
    activate_with(review={"enabled": True})


@pytest.mark.usefixtures("review_enabled")
def test_a_state_directory_refusing_the_write_leaves_the_unit_going_on_with_one_logged_failure(
    tmp_path: Path,
) -> None:
    (tmp_path / "ok").mkdir()
    baseline = build(tmp_path / "ok", fresh(tmp_path / "ok"))
    refused = tmp_path / "refused"
    refused.mkdir()
    (refused / VERDICTS).mkdir()  # a directory where the file goes: the replace is refused
    recorder = fresh(refused)

    outcome = build(refused, recorder)

    assert outcome == baseline
    assert recorder.store.get(UNIT_ID).state == IN_REVIEW
    failures = [line for line in recorder.logged if "verdict" in line.lower()]
    assert len(failures) == 1, recorder.logged


def test_with_review_disabled_no_entry_is_written(tmp_path: Path) -> None:
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    activate_with(review={"enabled": True})
    build(tmp_path / "on", fresh(tmp_path / "on"))
    activate_with(review={"enabled": False})

    build(tmp_path / "off", fresh(tmp_path / "off"))

    assert (tmp_path / "on" / VERDICTS).exists(), "with review enabled the round is recorded"
    assert not (tmp_path / "off" / VERDICTS).exists()


def test_no_source_reads_the_verdict_file_outside_the_recording_module_and_status() -> None:
    named = {
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in SOURCE_ROOT.rglob("*.py")
        if NAMES.search(path.read_text())
    }

    assert "graph/nodes.py" in named, "the review node records through the module"
    assert named <= ALLOWED, f"read or named outside the allowed: {sorted(named - ALLOWED)}"
