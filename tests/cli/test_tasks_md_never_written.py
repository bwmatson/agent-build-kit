"""A tick, a replan and a planning pass leave every `tasks.md` as it was, old tags included
(spec: tasks-tag-rewrite, the pipeline never rewrites a tasks file)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import Replan, answer, planned, tagged_md, tick, ticking_replan
from tests.cli.tags_fix_support import OLD_E2E_TAG, OLD_UNIT_TEST_TAG, digest_of

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD = tagged_md(OLD_UNIT_TEST_TAG, OLD_E2E_TAG)
NEW = tagged_md("unit-test", "e2e-test")
PLAN = answer(planned("other/1", (1,)), planned("other/2", (2,)))


def files(run: Replan) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in run.inst.changes_dir.glob("*/tasks.md")}


def with_old_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    """Two changes with old tags, `feature` already planned as the rewritten text reads."""
    run = ticking_replan(tmp_path, monkeypatch, {"feature": OLD, "other": OLD})
    run.record("feature", sizing=cli.sizing_digest(), hash=digest_of(tmp_path, NEW))
    run.runtime.answer = PLAN
    return run


def test_a_tick_leaves_the_tasks_files_unchanged_and_plans_only_the_change_not_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = with_old_tags(tmp_path, monkeypatch)
    before = files(run)

    _, out = tick(run, capsys)

    assert files(run) == before
    assert run.calls == 1, out


def test_a_replan_leaves_the_tasks_files_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = with_old_tags(tmp_path, monkeypatch)
    before = files(run)

    code, out = run.run(capsys, "other")

    assert code == 0, out
    assert files(run) == before
    calls = run.calls
    _, out = tick(run, capsys)
    assert run.calls == calls, "the tick plans neither change again: " + out


def test_a_planning_pass_leaves_the_tasks_files_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = with_old_tags(tmp_path, monkeypatch)
    before = files(run)

    cli.plan_all(run.inst, store=run.store)

    assert files(run) == before
    assert run.calls == 1
