"""The rates read what the pipeline really records: the outcome sweep marks a unit landed by the
pipeline, and the audit file holds the result (spec: auto-land, audited units in the rates)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.config import ReviewConfig
from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline import audit_record
from agent_build_kit.pipeline.review_outcome import with_outcome
from agent_build_kit.pipeline.review_rates import ClassGate, recorded_gates
from agent_build_kit.pipeline.units import UnitState
from tests.factories import commit, init_repo, stored_unit
from tests.forges.stand_in import StandInForge

UID = "add-marker/1"
REPO = RepoId(forge="stand_in", account="example", name="app")
AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
REVIEW = ReviewConfig.model_validate(
    {
        "enabled": True,
        "classes": {"docs": ["docs/**"]},
        "auto_land": {"min_samples": 1, "min_clean_rate": 0.5},
    }
)


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    """The verdict file, holding the record the outcome sweep made of a unit the pipeline
    landed, and the audit file's path."""
    checkout = init_repo(tmp_path / "app")
    commit(checkout, "base.txt")
    history = (
        {"state": "running", "at": AT.isoformat()},
        {"state": "merged", "at": AT.isoformat(), "cause": "auto_landed"},
    )
    unit = stored_unit(UID, state=UnitState.MERGED, pr=7, history=history)
    forge = StandInForge()
    forge.merged[7] = "a" * 40
    given = {UID: {"final": True, "unit_class": "docs", "brief": True, "evidence_tier": "auto"}}
    records = with_outcome(given, unit, forge=forge, repo=REPO, checkout=checkout, trunk="main")
    verdicts = tmp_path / "verdicts.json"
    verdicts.write_text(json.dumps(records))
    return verdicts, tmp_path / audit_record.AUDITS


def docs_gate(files: tuple[Path, Path]) -> ClassGate:
    verdicts, audits = files
    return recorded_gates(verdicts, REVIEW, audits)["docs"]


def test_the_sweep_marks_a_unit_the_pipeline_landed(files: tuple[Path, Path]) -> None:
    assert json.loads(files[0].read_text())[UID]["auto_landed"] is True


def test_a_unit_landed_and_not_audited_is_no_sample(files: tuple[Path, Path]) -> None:
    audit_record.record_awaiting(files[1], unit=UID, unit_class="docs", at=AT)

    gate = docs_gate(files)

    assert gate.rates.samples == 0
    assert not gate.clears


def test_audited_ok_it_is_one_clean_sample(files: tuple[Path, Path]) -> None:
    audit_record.record_awaiting(files[1], unit=UID, unit_class="docs", at=AT)
    audit_record.record_result(files[1], unit=UID, result="ok", at=AT)

    gate = docs_gate(files)

    assert (gate.rates.samples, gate.rates.clean) == (1, 1)
    assert gate.clears


def test_audited_wrong_it_is_one_sample_that_is_not_clean(files: tuple[Path, Path]) -> None:
    audit_record.record_awaiting(files[1], unit=UID, unit_class="docs", at=AT)
    audit_record.record_result(files[1], unit=UID, result="wrong", at=AT)

    gate = docs_gate(files)

    assert (gate.rates.samples, gate.rates.clean) == (1, 0)
    assert not gate.clears


def test_an_unreadable_audit_file_counts_no_audit(files: tuple[Path, Path]) -> None:
    files[1].write_text("not json")

    assert docs_gate(files).rates.samples == 0
