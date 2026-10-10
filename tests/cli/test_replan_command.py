"""`abk replan` selects changes, plans them now, and refuses what cannot be planned."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan, answer, planned, tasks_md

pytestmark = pytest.mark.usefixtures("scripted_engine")

ONE = answer(planned("feature/1", (1,)), planned("feature/2", (2,)))


def two_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(), other=tasks_md(1))
    run.record("feature")
    run.record("other")
    return run


def test_a_named_change_is_planned_and_others_are_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = two_changes(tmp_path, monkeypatch)

    code, _ = run.run(capsys, "feature", reply=ONE)

    assert code == 0
    assert run.calls == 1
    assert {u.id for u in run.store.all()} == {"feature/1", "feature/2"}


def test_a_unit_id_plans_its_change_and_says_which(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = two_changes(tmp_path, monkeypatch)

    code, out = run.run(capsys, "feature/2", reply=ONE)

    assert code == 0
    assert run.calls == 1
    assert "feature/2" in out
    assert "feature" in out.replace("feature/", "")
    assert {u.change for u in run.store.all()} == {"feature"}


def test_all_plans_every_active_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = two_changes(tmp_path, monkeypatch)

    code, _ = run.run(capsys, "--all", reply=ONE)

    assert code == 0
    assert run.calls == 2


def test_failed_plans_only_changes_that_failed_or_gave_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(), other=tasks_md(1), third=tasks_md(1))
    run.record("feature")
    run.record("other", ok=False, attempts=3)
    run.record("third", ok=False, attempts=1)

    run.run(capsys, "--failed", reply=answer(planned("other/1", (1,))))

    assert run.calls == 2


def test_the_count_of_model_calls_is_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = two_changes(tmp_path, monkeypatch)

    _, out = run.run(capsys, "--all", reply=ONE)

    assert "2 model call" in out


def test_no_selector_lists_each_change_with_its_plan_state_and_plans_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path,
        monkeypatch,
        feature=tasks_md(),
        other=tasks_md(1),
        third=tasks_md(1),
        fourth=tasks_md(1),
    )
    run.record("feature")
    run.record("other", ok=False, attempts=2)
    run.record("third", ok=False, attempts=3)

    code, out = run.run(capsys)

    assert code == 2
    assert run.calls == 0
    line = {
        name: next(ln for ln in out.splitlines() if name in ln)
        for name in ("feature", "other", "third", "fourth")
    }
    assert "planned" in line["feature"]
    assert "failing 2/3" in line["other"]
    assert "given up" in line["third"]
    assert "never planned" in line["fourth"]
    assert "abk replan" in out
    assert run.records["other"]["attempts"] == 2


def test_an_unknown_name_is_refused_and_nothing_is_planned_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = two_changes(tmp_path, monkeypatch)

    code, out = run.run(capsys, "feature", "nope", reply=ONE)

    assert code == 1
    assert "nope" in out
    assert run.calls <= 1


def test_a_change_without_a_tasks_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = two_changes(tmp_path, monkeypatch)
    (run.inst.changes_dir / "empty").mkdir()

    code, out = run.run(capsys, "empty", reply=ONE)

    assert code == 1
    assert "empty" in out
    assert "tasks.md" in out
    assert run.calls == 0


def test_a_change_with_tag_errors_is_refused_and_says_to_run_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = two_changes(tmp_path, monkeypatch)
    run.write("broken", "# Tasks\n\n## 1. [nowhere] [tier1] G\n\n- [ ] 1.1 Test: it.\n")

    code, out = run.run(capsys, "broken", reply=ONE)

    assert code == 1
    assert "abk tags" in out
    assert run.calls == 0


def test_a_failed_plan_exits_with_one_and_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = two_changes(tmp_path, monkeypatch)
    run.runtime.ok = False
    run.runtime.error = "the model is unavailable"

    code, _ = run.run(capsys, "feature")

    assert code == 1
    assert run.records["feature"]["ok"] is False


def test_the_give_up_message_names_replan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md())
    run.runtime.ok = False
    run.runtime.error = "the model is unavailable"
    run.record("feature", ok=False, attempts=2)

    capsys.readouterr()
    cli.plan_all(run.inst, store=run.store)

    seen = capsys.readouterr()
    text = seen.out + seen.err
    assert "giving up" in text
    assert "abk replan" in text
