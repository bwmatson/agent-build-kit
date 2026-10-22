"""A verdict is recorded after every review round (spec: review-verdict)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import telemetry
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.stack_runner import change_dir_of
from agent_build_kit.pipeline.unit_store import E2eState, UnitStore
from agent_build_kit.pipeline.units import HELD
from agent_build_kit.pipeline.verdict import ClassHistory, GateResult, ReviewTier, VerdictFacts
from agent_build_kit.pipeline.verdict_record import VERDICTS, latest_verdict, record_verdict
from tests.factories import activate_with, unit
from tests.graph.test_build_path import build, fresh
from tests.otlp import enabled
from tests.runner_fakes import Killed, Recorder, approving, rejecting

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
        e2e_state=E2eState.PASSED,
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
        repo="app",
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
    pending = green(kind=TestTier.E2E_TEST, e2e_state=None)

    interim = record(tmp_path / VERDICTS, pending, history=TRACK_RECORD)[UNIT_ID]
    final = record(
        tmp_path / VERDICTS, pending.model_copy(update={"final": True}), round=2,
        history=TRACK_RECORD,
    )[UNIT_ID]  # fmt: skip

    assert (interim["final"], interim["tier"]) == (False, "auto")
    assert (final["final"], final["tier"]) == (True, "full")
    assert final["reason"] == "the e2e-test gate has no result"


def test_a_deferred_unit_is_recorded_light_with_the_deferral_as_the_reason(
    tmp_path: Path,
) -> None:
    deferred = VerdictFacts(
        kind=TestTier.E2E_TEST,
        red_first=GateResult.PASSED,
        unit_test=GateResult.PASSED,
        e2e_state=E2eState.DEFERRED,
        classification=ReviewTier.AUTO,
        final=True,
    )

    entry = record(tmp_path / VERDICTS, deferred, history=TRACK_RECORD)[UNIT_ID]

    assert (entry["tier"], entry["evidence_tier"]) == ("light", "light")
    assert entry["reason"] == "the e2e-test result was deferred to verify"


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
    assert entry["paths"] == ["src/app.py"], "what the fake build committed"
    assert entry["lines"] > 0


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


def killed(**kwargs: Any) -> str:
    raise Killed


def round_one(tmp_path: Path, reply: str, **runner: Any) -> tuple[Any, dict[str, Any]]:
    """The recorder after one round whose reply is `reply`, and that round's entry."""
    recorder = fresh(tmp_path)
    recorder.verdicts = [reply]
    for name, value in runner.items():
        setattr(recorder, name, value)
    with pytest.raises(Killed):
        build(tmp_path, recorder, run_rework_review=killed)
    return recorder, entries(tmp_path)[UNIT_ID]


def classified(tier: str, **fields: Any) -> str:
    return json.dumps({"approved": False, "feedback": "x", "classification": tier, **fields})


def test_a_round_over_a_protected_path_is_recorded_full_naming_the_path(tmp_path: Path) -> None:
    _, entry = round_one(
        tmp_path, classified("auto"), changed=("db/migrations/0001.sql",), changed_lines=3
    )

    assert entry["tier"] == "full"
    assert "db/migrations/0001.sql" in entry["reason"]
    assert entry["paths"] == ["db/migrations/0001.sql"]


def test_a_required_finding_in_the_round_makes_it_full(tmp_path: Path) -> None:
    finding = {"file": "src/app.py", "summary": "the lock leaks", "required": True}
    _, entry = round_one(tmp_path, classified("light", findings=[finding]))

    assert entry["tier"] == "full"
    assert "open required finding" in entry["reason"]


def test_a_configured_class_matching_every_changed_path_names_the_entry(tmp_path: Path) -> None:
    activate_with(review={"enabled": True, "classes": {"docs": ["docs/**"]}})

    _, entry = round_one(tmp_path, classified("auto"), changed=("docs/a.md", "docs/b.md"))

    assert entry["unit_class"] == "docs"


def test_the_verdict_is_computed_under_the_installations_auto_land_policy(tmp_path: Path) -> None:
    activate_with(review={"enabled": True, "auto_land": {"min_samples": 3}})

    _, entry = round_one(tmp_path, classified("auto"))

    assert "fewer than the 3 needed" in entry["reason"]


def test_a_flagged_group_the_unit_builds_makes_the_round_full(tmp_path: Path) -> None:
    tasks = change_dir_of(tmp_path / "meta", "add-marker") / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("## 1. [app] [unit-test] [contract] Title\n\n- [ ] 1.1 Test: x\n")

    _, entry = round_one(tmp_path, classified("auto"))

    assert entry["tier"] == "full"
    assert "flagged [contract]" in entry["reason"]


def test_the_planner_accuracy_point_carries_the_units_repo(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(review_tier="auto")])
    recorder = Recorder(store)
    recorder.verdicts = [classified("auto")]

    with enabled() as collector:
        assert telemetry.init() is True
        with pytest.raises(Killed):
            build(tmp_path, recorder, run_rework_review=killed)
        telemetry.shutdown()

    (point,) = collector.metric("abk.planner.accuracy")
    assert point.attributes["repo"] == unit().repo


def test_the_latest_verdict_is_the_entry_record_verdict_wrote(tmp_path: Path) -> None:
    path = tmp_path / VERDICTS
    written = record_verdict(
        path,
        unit=UNIT_ID,
        change="add-marker",
        round=1,
        unit_class="app/unit-test",
        repo="app",
        facts=green(),
    )

    assert latest_verdict(path, UNIT_ID) == written


@pytest.mark.parametrize("content", [None, "{not json", "[]", "{}", '{"other/1": {}}'])
def test_a_missing_unreadable_or_unrelated_record_gives_no_verdict(
    tmp_path: Path, content: str | None
) -> None:
    path = tmp_path / VERDICTS
    if content is not None:
        path.write_text(content)

    assert latest_verdict(path, UNIT_ID) is None


def test_a_record_that_cannot_be_read_as_a_file_gives_no_verdict(tmp_path: Path) -> None:
    path = tmp_path / VERDICTS
    path.mkdir()

    assert latest_verdict(path, UNIT_ID) is None
