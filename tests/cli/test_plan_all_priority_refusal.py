"""A plan refused for an edge to a less urgent unit is recorded, shown, and fed back to the next
attempt (spec: planner-priority-edges)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.plan_outage_fakes import raises, service
from tests.cli.replan_driver import OPT_OUT, Replan, answer, planned
from tests.fake_clock import install

pytestmark = pytest.mark.usefixtures("scripted_engine")

INVERTED = answer(planned("feature/1", (1,)), planned("feature/2", (2,), depends_on=("feature/1",)))
EXCUSED = INVERTED.replace(
    '"depends_on": ["feature/1"]',
    '"depends_on": ["feature/1"], "needs_less_urgent": {"feature/1": "it adds the helper"}',
)


def tasks_md(first: int = 3, second: int = 1) -> str:
    text = f"# Tasks\n\n{OPT_OUT}\n"
    for number, value in ((1, first), (2, second)):
        text += f"## {number}. [app] [unit-test] Group {number}\n\nPriority: {value}\n\n"
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> Replan:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    code, _ = run.run(capsys, "feature", reply=INVERTED)
    assert code == 1
    return run


def test_the_refusal_is_recorded_with_the_unit_ids_and_its_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused(tmp_path, monkeypatch, capsys)

    record = run.records["feature"]
    assert record["ok"] is False
    assert record["units"] == ["feature/1", "feature/2"]
    assert "feature/2" in record["reason"] and "feature/1" in record["reason"]
    assert "\n" not in record["reason"]


def test_a_bare_replan_lists_the_attempt_and_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused(tmp_path, monkeypatch, capsys)

    _, out = run.run(capsys)

    line = next(line for line in out.splitlines() if line.startswith("feature:"))
    assert f"failing 1/3: {run.records['feature']['reason']}" in line


def test_a_third_refusal_is_given_up_and_replan_exits_one_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    run.record("feature", attempts=2, ok=False, units=["feature/1"], reason="an earlier one")
    run.runtime.answer = INVERTED
    cli.plan_all(run.inst, store=run.store)

    assert run.records["feature"]["attempts"] == 3
    _, listing = run.run(capsys)

    code, out = run.run(capsys, "feature", reply=INVERTED)

    assert code == 1
    assert "Traceback" not in out
    assert "given up" in listing


def test_the_second_attempt_ends_with_the_previous_refusal_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused(tmp_path, monkeypatch, capsys)
    reason = run.records["feature"]["reason"]

    run.runtime.answer = INVERTED
    cli.plan_all(run.inst, store=run.store)

    assert run.runtime.requests[-1].prompt.rstrip().endswith(reason)
    assert reason not in run.runtime.requests[0].prompt


def test_a_replan_that_counts_from_none_still_feeds_the_reason_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused(tmp_path, monkeypatch, capsys)
    reason = run.records["feature"]["reason"]

    run.run(capsys, "feature", reply=INVERTED)

    assert run.runtime.requests[-1].prompt.rstrip().endswith(reason)


def test_an_edited_tasks_file_carries_no_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused(tmp_path, monkeypatch, capsys)
    reason = run.records["feature"]["reason"]
    run.write("feature", tasks_md(3, 2))

    run.runtime.answer = INVERTED
    cli.plan_all(run.inst, store=run.store)

    assert reason
    assert reason not in run.runtime.requests[-1].prompt


def test_a_failed_call_leaves_nothing_to_feed_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused(tmp_path, monkeypatch, capsys)
    reason = run.records["feature"]["reason"]
    run.runtime.ok, run.runtime.error = False, "boom"
    cli.plan_all(run.inst, store=run.store)
    assert run.records["feature"]["units"] == []

    run.runtime.ok, run.runtime.error = True, ""
    run.runtime.answer = INVERTED
    cli.plan_all(run.inst, store=run.store)

    assert reason
    assert reason not in run.runtime.requests[-1].prompt


def test_an_outage_after_a_refusal_leaves_nothing_to_feed_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch)
    run = refused(tmp_path, monkeypatch, capsys)
    reason = run.records["feature"]["reason"]
    run.runtime.act = raises(service())
    assert cli.plan_all(run.inst, store=run.store)["feature"].status == "waiting"

    run.runtime.act = None
    run.run(capsys, "feature", reply=INVERTED)

    prompt = run.runtime.requests[-1].prompt
    assert reason
    assert reason not in prompt
    assert "Your previous plan was refused" not in prompt


def test_a_later_accepted_plan_clears_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = refused(tmp_path, monkeypatch, capsys)
    assert run.records["feature"]["reason"]

    code, _ = run.run(capsys, "feature", reply=EXCUSED)

    assert code == 0
    assert run.records["feature"]["ok"] is True
    assert "reason" not in run.records["feature"]
