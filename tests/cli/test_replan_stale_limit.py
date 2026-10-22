"""`abk replan --stale --limit N` plans the most urgent stale changes first and skips and lists
the ones that wait or have given up (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest
from tests.cli.plan_outage_fakes import raises, service
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tagged_md
from tests.cli.tags_fix_support import OLD_UNIT_TEST_TAG, recorded_before_the_tag_was_renamed
from tests.fake_clock import install

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD_SIZING = "a-digest-of-other-ceilings"
SINCE = "2030-01-01T09:00:00+00:00"
UNTIL = "2030-01-01T09:05:00+00:00"


def change_md(name: str, priority: int | None = None) -> str:
    """A one-group tasks.md whose title names the change, so the planner stand-in can tell
    which change it is asked about; `priority` is its `Priority:` line."""
    line = f"Priority: {priority}\n\n" if priority is not None else ""
    return (
        "# Tasks\n\nAcceptance: none — a fixture about replanning\n\n"
        f"## 1. [app] [unit-test] Work of {name}\n\n{line}"
        "- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"
    )


def stale_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, priorities: dict[str, int | None]
) -> Replan:
    """A planning repo with one change per name, each planned under other ceilings, and a
    planner that answers for whichever change it is asked about."""
    changes = {n: change_md(n, p) for n, p in priorities.items()}
    run = Replan(tmp_path, monkeypatch, **changes)  # pyrefly: ignore[bad-argument-type]
    enable_review(run)
    for name in priorities:
        run.record(name, sizing=OLD_SIZING)
    replies = {f"Work of {n}": answer(planned(f"{n}/1", (1,))) for n in priorities}

    def act(request: AgentRequest) -> None:
        run.runtime.answer = next(text for key, text in replies.items() if key in request.prompt)

    run.runtime.act = act
    return run


def planned_changes(run: Replan) -> set[str]:
    return {unit.change for unit in run.store.all()}


def line_with(out: str, *words: str) -> str:
    return next(line for line in out.splitlines() if all(word in line for word in words))


def test_limit_plans_the_most_urgent_changes_and_lists_the_rest_as_not_yet_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = stale_run(
        tmp_path,
        monkeypatch,
        {"alpha": None, "bravo": None, "charlie": 1, "delta": None, "echo": 1},
    )

    code, out = run.run(capsys, "--stale", "--limit", "2")

    assert code == 0
    assert run.calls == 2
    assert planned_changes(run) == {"charlie", "echo"}
    for change in ("alpha", "bravo", "delta"):
        assert "not yet planned" in line_with(out, change)


def test_equal_priorities_go_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = stale_run(tmp_path, monkeypatch, {"delta": None, "bravo": None, "charlie": None})

    code, _ = run.run(capsys, "--stale", "--limit", "2")

    assert code == 0
    assert planned_changes(run) == {"bravo", "charlie"}


def test_a_change_that_is_waiting_or_has_given_up_is_skipped_and_listed_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch)
    run = stale_run(tmp_path, monkeypatch, {"alpha": 1, "bravo": 1, "charlie": None})
    run.record(
        "alpha",
        sizing=OLD_SIZING,
        ok=False,
        attempts=1,
        waiting="network",
        waits=1,
        since=SINCE,
        until=UNTIL,
        reason="API Error: unreachable",
    )
    run.record(
        "bravo",
        sizing=OLD_SIZING,
        ok=False,
        attempts=run.inst.max_plan_attempts,
        reason="the graph call failed",
    )

    code, out = run.run(capsys, "--stale", "--limit", "3")

    assert code == 0
    assert run.calls == 1
    assert planned_changes(run) == {"charlie"}
    assert "waiting for the network" in line_with(out, "alpha", "skipped")
    given_up = line_with(out, "bravo", "skipped")
    assert "given up" in given_up and "--failed" in given_up


def test_an_outage_ends_the_run_says_the_rest_were_not_tried_and_uses_no_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    install(monkeypatch)
    run = stale_run(tmp_path, monkeypatch, {"alpha": None, "bravo": None, "charlie": None})
    run.runtime.act = raises(service())

    code, out = run.run(capsys, "--stale", "--limit", "3")

    assert code == 1
    assert run.calls == 1
    assert planned_changes(run) == set()
    assert "alpha: waiting for the model service" in out
    for change in ("bravo", "charlie"):
        assert "not tried" in line_with(out, change)
    assert run.records["alpha"]["attempts"] == 0
    assert run.records["alpha"]["waiting"] == "service"
    assert run.records["bravo"].get("waiting") is None


def test_a_change_that_gave_up_on_text_since_edited_is_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = stale_run(tmp_path, monkeypatch, {"alpha": None})
    run.record(
        "alpha",
        sizing=OLD_SIZING,
        hash="the-digest-of-the-text-before-the-edit",
        ok=False,
        attempts=run.inst.max_plan_attempts,
        reason="the graph call failed",
    )

    code, out = run.run(capsys, "--stale")

    assert code == 0
    assert planned_changes(run) == {"alpha"}
    assert "skipped" not in out


def test_a_plan_recorded_before_the_tag_was_renamed_that_gave_up_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = tagged_md(OLD_UNIT_TEST_TAG)
    run = Replan(tmp_path, monkeypatch, alpha=text)
    enable_review(run)
    run.record(
        "alpha",
        hash=recorded_before_the_tag_was_renamed(text),
        sizing=OLD_SIZING,
        ok=False,
        attempts=run.inst.max_plan_attempts,
        reason="the graph call failed",
    )

    code, out = run.run(capsys, "--stale")

    assert code == 0
    assert run.calls == 0
    line = line_with(out, "alpha", "skipped")
    assert "given up" in line and "--failed" in line
    assert planned_changes(run) == set()


def test_limit_with_names_keeps_the_first_of_them_by_urgency_and_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = stale_run(tmp_path, monkeypatch, {"alpha": None, "bravo": None})

    code, out = run.run(capsys, "bravo", "alpha", "--limit", "1")

    assert code == 0
    assert planned_changes(run) == {"alpha"}
    assert "not yet planned" in line_with(out, "bravo")


def test_a_limit_below_one_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = stale_run(tmp_path, monkeypatch, {"alpha": None})

    code, out = run.run(capsys, "alpha", "--limit", "0")

    assert code == 2
    assert "--limit must be at least 1" in out
    assert run.calls == 0
