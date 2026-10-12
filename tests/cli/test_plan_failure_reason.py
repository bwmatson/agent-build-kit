"""A failed plan keeps the first line of why, bounded and redacted, whatever raised (spec:
unit-scheduling).

The planner is the runtime stand-in, failing as a runtime does: a failed result, or an
exception from `run`. The reason is what `planned.json` holds, so it is read from there.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.plan_outage_fakes import raises
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.redaction_fakes import NAME, SECRET, known

pytestmark = pytest.mark.usefixtures("scripted_engine")

CHANGE = "feature"
LIMIT = 300


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    return Replan(tmp_path, monkeypatch, feature=tasks_md(1))


def test_a_planner_failure_stores_its_first_line_cut_to_three_hundred_characters(
    run: Replan,
) -> None:
    run.runtime.ok = False
    run.runtime.error = "overloaded " + "x" * 400 + "\nsecond line"

    assert cli.plan_all(run.inst, store=run.store)[CHANGE].status == "failed"

    reason = run.records[CHANGE]["reason"]
    assert reason.startswith("the graph call failed: overloaded xxx")
    assert len(reason) == LIMIT
    assert "second line" not in reason


def test_any_other_exception_stores_its_name_and_first_line(run: Replan) -> None:
    run.runtime.act = raises(ValueError("the reply could not be read\nat line 4"))

    cli.plan_all(run.inst, store=run.store)

    assert run.records[CHANGE]["reason"] == "ValueError: the reply could not be read"


def test_a_value_the_active_set_knows_is_absent_from_the_record(run: Replan) -> None:
    run.runtime.act = raises(RuntimeError(f"401 for key {SECRET}"))

    with known({NAME: SECRET}):
        cli.plan_all(run.inst, store=run.store)

    stored = (run.inst.state_dir / "planned.json").read_text()
    assert SECRET not in stored
    assert run.records[CHANGE]["reason"].startswith("RuntimeError: 401 for key")


def test_a_refusal_keeps_the_units_it_returned_and_its_reason_redacted(run: Replan) -> None:
    run.runtime.answer = answer(planned("feature/1", (1,)) | {"repo": SECRET})

    with known({NAME: SECRET}):
        cli.plan_all(run.inst, store=run.store)

    assert SECRET not in (run.inst.state_dir / "planned.json").read_text()
    record = run.records[CHANGE]
    assert record["units"] == ["feature/1"]
    assert record["reason"]
