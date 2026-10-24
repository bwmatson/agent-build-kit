"""A failed verify demotes the class of each auto-landed unit of the change; a passing verify, or a
change with no auto-landed unit, demotes nothing (spec: class-demotion, a verify failure demotes
the classes of the change's auto-landed units).

`verify_ready` is real and the verification is injected, as `test_cli_pipeline` does; the verdict
records say which units the pipeline landed."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import demotion_record
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.verdict_record import VERDICTS
from agent_build_kit.pipeline.verify import Verification, VerifyRecord
from tests.conftest import make_installation
from tests.demotion_triggers_support import merged_unit, record


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        review=dict(
            enabled=True,
            classes={"docs": ["docs/**"], "code": ["src/**"]},
            auto_land=dict(classes=["docs", "code"]),
        ),
    )


def land(inst: Installation, *units: tuple[StoredUnit, str, bool]) -> list[StoredUnit]:
    """Record a final verdict of the class for each unit, landed by the pipeline or not."""
    records = {
        unit.id: record("clean", unit_class=unit_class, auto=auto)
        for unit, unit_class, auto in units
    }
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    (inst.state_dir / VERDICTS).write_text(json.dumps(records))
    return [unit for unit, _, _ in units]


def verifier(*failing: str, calls: list[str] | None = None) -> Callable[[str, list], Verification]:
    def verify(change: str, units: list) -> Verification:
        if calls is not None:
            calls.append(change)
        merged = sorted(u.id for u in units if u.carries(change) and u.pr)
        return Verification(change=change, passed=change not in failing, units=merged)

    return verify


def demoted(inst: Installation) -> dict[str, dict]:
    return demotion_record.read_demotions(inst.state_dir / demotion_record.DEMOTIONS)


def test_a_failed_verify_demotes_the_class_of_the_auto_landed_unit_and_not_a_persons(
    inst: Installation,
) -> None:
    units = land(
        inst,
        (merged_unit("feature/1", auto=True, pr=1), "docs", True),
        (merged_unit("feature/2", pr=2), "code", False),
    )
    calls: list[str] = []

    may_archive = cli.verify_ready(inst, units, verify=verifier("feature", calls=calls))

    assert list(demoted(inst)) == ["docs"]
    assert [(t["trigger"], t["unit"]) for t in demoted(inst)["docs"]["triggers"]] == [
        ("verify", "feature/1")
    ]
    # Verify's own rules: the failure is recorded, blocks archiving and is not retried.
    last = VerifyRecord(inst.state_dir / "verified.json").get("feature")
    assert last is not None and not last.passed
    assert not may_archive("feature")
    cli.verify_ready(inst, units, verify=verifier("feature", calls=calls))
    assert calls == ["feature"]


def test_a_failed_verify_of_a_change_with_no_auto_landed_unit_demotes_nothing(
    inst: Installation,
) -> None:
    units = land(
        inst,
        (merged_unit("people/1", change="people", pr=1), "docs", False),
        (merged_unit("landed/1", change="landed", auto=True, pr=2), "code", True),
    )

    cli.verify_ready(inst, units, verify=verifier("people", "landed"))

    assert list(demoted(inst)) == ["code"]


def test_a_passing_verify_demotes_nothing(inst: Installation) -> None:
    units = land(
        inst,
        (merged_unit("good/1", change="good", auto=True, pr=1), "docs", True),
        (merged_unit("bad/1", change="bad", auto=True, pr=2), "code", True),
    )

    cli.verify_ready(inst, units, verify=verifier("bad"))

    assert list(demoted(inst)) == ["code"]
