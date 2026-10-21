"""A verdict is recorded after every review round (spec: review-verdict)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.units import HELD
from agent_build_kit.pipeline.verdict import ClassHistory, GateResult, ReviewTier, VerdictFacts
from agent_build_kit.pipeline.verdict_record import VERDICTS, record_verdict
from tests.factories import activate_with
from tests.graph.test_build_path import build, fresh
from tests.runner_fakes import Killed, approving, rejecting

ROOT = Path(__file__).resolve().parents[2]
UNIT_ID = "add-marker/1"
TRACK_RECORD = ClassHistory(samples=100, clean=100)
FIELDS = {
    "unit",
    "change",
    "round",
    "final",
    "unit_class",
    "planned_estimate",
    "classification",
    "drivers",
    "evidence_tier",
    "tier",
    "reason",
    "paths",
    "lines",
    "brief",
}


@pytest.fixture(autouse=True)
def review_enabled() -> None:
    activate_with(review={"enabled": True})


def green(**fields: Any) -> VerdictFacts:
    base: dict[str, Any] = dict(
        kind=TestTier.UNIT_TEST,
        red_first=GateResult.PASSED,
        unit_test=GateResult.PASSED,
        e2e_test=GateResult.PASSED,
        classification=ReviewTier.AUTO,
    )
    return VerdictFacts(**{**base, **fields})


def record(
    path: Path, facts: VerdictFacts, *, unit: str = UNIT_ID, round: int = 1, **fields: Any
) -> dict[str, Any]:
    record_verdict(
        path,
        unit=unit,
        change="add-marker",
        round=round,
        unit_class="app/unit-test",
        facts=facts,
        **fields,
    )
    return json.loads(path.read_text())


def entries(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / VERDICTS).read_text())


# --- the entry --------------------------------------------------------------------


def test_an_interim_entry_holds_every_field_the_spec_lists(tmp_path: Path) -> None:
    facts = green(
        planned_estimate=ReviewTier.LIGHT,
        protected_paths=("db/migrations/0001.sql",),
        classification=ReviewTier.LIGHT,
    )

    written = record(
        tmp_path / VERDICTS,
        facts,
        drivers=("group 2",),
        paths=("db/migrations/0001.sql", "src/app.py"),
        lines=41,
    )

    assert written[UNIT_ID] == {
        "unit": UNIT_ID,
        "change": "add-marker",
        "round": 1,
        "final": False,
        "unit_class": "app/unit-test",
        "planned_estimate": "light",
        "classification": "light",
        "drivers": ["group 2"],
        "evidence_tier": "full",
        "tier": "full",
        "reason": "it changed the protected path db/migrations/0001.sql",
        "paths": ["db/migrations/0001.sql", "src/app.py"],
        "lines": 41,
        "brief": False,
    }


def test_no_estimate_is_recorded_as_none(tmp_path: Path) -> None:
    written = record(tmp_path / VERDICTS, green())

    assert written[UNIT_ID]["planned_estimate"] is None


def test_a_later_round_replaces_the_units_entry_and_keeps_the_others(tmp_path: Path) -> None:
    path = tmp_path / VERDICTS
    record(path, green(), unit="add-marker/2")
    record(path, green())

    written = record(path, green(final=True), round=2)

    assert set(written) == {UNIT_ID, "add-marker/2"}
    assert (written[UNIT_ID]["round"], written[UNIT_ID]["final"]) == (2, True)
    assert written["add-marker/2"]["round"] == 1


def test_a_pending_e2e_test_is_met_in_the_interim_entry_and_missing_in_the_final(
    tmp_path: Path,
) -> None:
    pending = green(kind=TestTier.E2E_TEST, e2e_test=GateResult.PENDING)

    interim = record(tmp_path / VERDICTS, pending, history=TRACK_RECORD)[UNIT_ID]
    final = record(
        tmp_path / VERDICTS, pending.model_copy(update={"final": True}), round=2,
        history=TRACK_RECORD,
    )[UNIT_ID]  # fmt: skip

    assert (interim["final"], interim["tier"]) == (False, "auto")
    assert (final["final"], final["tier"]) == (True, "full")
    assert final["reason"] == "the e2e-test gate has no result"


def test_a_unit_with_no_history_has_an_evidence_tier_below_its_tier(tmp_path: Path) -> None:
    written = record(tmp_path / VERDICTS, green())[UNIT_ID]

    assert (written["evidence_tier"], written["tier"]) == ("auto", "light")


def test_the_file_is_replaced_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / VERDICTS
    record(path, green())
    before = path.read_text()

    def interrupt(src: object, dst: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupt)
    with pytest.raises(KeyboardInterrupt):
        record(path, green(), unit="add-marker/2")
    monkeypatch.undo()

    assert path.read_text() == before
    assert [e.name for e in tmp_path.iterdir() if e.name.endswith(".tmp")] == []


def test_the_architecture_doc_lists_the_file_with_the_other_state_files() -> None:
    state = (ROOT / "docs" / "architecture.md").read_text().split("## State on disk")[1]
    rows = [line for line in state.splitlines() if line.startswith("| `")]

    assert any(line.startswith(f"| `{VERDICTS}`") for line in rows)


# --- the review node records each round ---------------------------------------------


def test_a_round_that_asks_for_rework_records_one_interim_entry(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the lock is not released")]

    def killed(**kwargs: Any) -> str:
        raise Killed

    with pytest.raises(Killed):
        build(tmp_path, recorder, run_rework_review=killed)

    written = entries(tmp_path)
    assert list(written) == [UNIT_ID]
    entry = written[UNIT_ID]
    assert set(entry) == FIELDS
    assert (entry["unit"], entry["change"], entry["round"]) == (UNIT_ID, "add-marker", 1)
    assert (entry["final"], entry["brief"]) == (False, False)
    assert entry["unit_class"] == "app/unit-test"
    assert entry["planned_estimate"] is None
    assert entry["tier"] == "full", "a reply with no classification is read as full"


def test_the_round_that_approves_replaces_it_with_a_final_entry(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the lock is not released"), approving()]

    build(tmp_path, recorder)

    written = entries(tmp_path)
    assert list(written) == [UNIT_ID]
    assert (written[UNIT_ID]["round"], written[UNIT_ID]["final"]) == (2, True)


def test_a_round_that_holds_the_unit_for_a_person_leaves_an_interim_entry_only(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [json.dumps({"approved": False, "feedback": "x", "needs_human": True})]

    build(tmp_path, recorder)

    assert recorder.store.get(UNIT_ID).state == HELD
    written = entries(tmp_path)
    assert (written[UNIT_ID]["round"], written[UNIT_ID]["final"]) == (1, False)
