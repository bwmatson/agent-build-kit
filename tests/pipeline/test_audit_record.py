"""The audit record: a picked unit awaits a result, the result replaces the waiting record."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline import audit_record
from agent_build_kit.pipeline.audit_record import NotAwaitingAudit
from tests import fake_clock
from tests.landing_support import UNIT, apply_review, landing, listed_review

ROOT = Path(__file__).resolve().parents[2]
FIRST = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / audit_record.AUDITS


def land_at_rate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rate: float) -> Path:
    """Land the one landable unit with the audit sample rate `rate`; the audit file's path."""
    landed = landing(tmp_path, monkeypatch)
    review = listed_review()
    audit = review.audit.model_copy(update={"sample_rate": rate})
    apply_review(landed.inst, review.model_copy(update={"audit": audit}))
    landed.land()
    return landed.inst.state_dir / audit_record.AUDITS


def test_landing_a_picked_unit_records_it_awaiting_with_its_class_and_the_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_clock.install(monkeypatch)
    audits = land_at_rate(tmp_path, monkeypatch, 1)

    record = audit_record.read_audits(audits)[UNIT]
    assert (record["state"], record["unit_class"]) == ("awaiting", "docs")
    assert datetime.fromisoformat(record["at"]) == fake_clock.START


def test_landing_a_unit_at_a_rate_of_zero_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audits = land_at_rate(tmp_path, monkeypatch, 0)

    assert audit_record.read_audits(audits) == {}


def test_a_result_replaces_the_waiting_record_with_the_result_and_the_time(path: Path) -> None:
    audit_record.record_awaiting(path, unit="c/1", unit_class="docs", at=FIRST)

    audit_record.record_result(path, unit="c/1", result="wrong", at=LATER)

    record = audit_record.read_audits(path)["c/1"]
    assert (record["state"], record["unit_class"]) == ("wrong", "docs")
    assert datetime.fromisoformat(record["at"]) == LATER


def test_a_result_for_a_unit_not_awaiting_audit_is_refused_and_nothing_is_recorded(
    path: Path,
) -> None:
    audit_record.record_awaiting(path, unit="c/1", unit_class="docs", at=FIRST)
    before = path.read_text()

    with pytest.raises(NotAwaitingAudit):
        audit_record.record_result(path, unit="c/2", result="ok", at=LATER)

    assert path.read_text() == before


def test_a_second_result_for_a_unit_is_refused(path: Path) -> None:
    audit_record.record_awaiting(path, unit="c/1", unit_class="docs", at=FIRST)
    audit_record.record_result(path, unit="c/1", result="ok", at=LATER)

    with pytest.raises(NotAwaitingAudit):
        audit_record.record_result(path, unit="c/1", result="wrong", at=LATER)

    assert audit_record.read_audits(path)["c/1"]["state"] == "ok"


def test_an_unreadable_file_is_refused_and_left_as_it_is(path: Path) -> None:
    path.write_text("not json")

    with pytest.raises(audit_record.UnreadableAudits):
        audit_record.record_awaiting(path, unit="c/1", unit_class="docs", at=FIRST)
    with pytest.raises(audit_record.UnreadableAudits):
        audit_record.record_result(path, unit="c/1", result="ok", at=LATER)

    assert path.read_text() == "not json"
    assert audit_record.audit_status_lines(path)[0].startswith("audits:")


def test_the_file_is_replaced_atomically(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit_record.record_awaiting(path, unit="c/1", unit_class="docs", at=FIRST)
    before = path.read_text()

    def interrupt(src: object, dst: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        audit_record.record_awaiting(path, unit="c/2", unit_class="docs", at=LATER)
    monkeypatch.undo()

    assert path.read_text() == before
    assert [e.name for e in path.parent.iterdir() if e.name.endswith(".tmp")] == []


def test_the_architecture_doc_lists_the_file_with_the_other_state_files() -> None:
    state = (ROOT / "docs" / "architecture.md").read_text().split("## State on disk")[1]
    rows = [line for line in state.splitlines() if line.startswith("| `")]

    assert any(line.startswith(f"| `{audit_record.AUDITS}`") for line in rows)
