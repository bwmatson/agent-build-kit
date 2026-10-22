"""The digest that decides whether a plan is current ignores the spelling of the test-kind tag,
and a plan recorded from the old spelling still counts as current for the rewritten text
(spec: tasks-tag-rewrite, a tag rewrite is not an edit of the specification)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.replan_driver import tagged_md, tick, ticking_replan
from tests.cli.tags_fix_support import (
    OLD_E2E_TAG,
    OLD_UNIT_TEST_TAG,
    digest_of,
    recorded_before_the_tag_was_renamed,
    run_tags,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD = tagged_md(OLD_UNIT_TEST_TAG, OLD_E2E_TAG)
NEW = tagged_md("unit-test", "e2e-test")


def test_the_digest_is_the_same_for_the_old_and_the_new_spelling(tmp_path: Path) -> None:
    assert digest_of(tmp_path, OLD) == digest_of(tmp_path, NEW)


def test_the_digest_still_moves_when_the_text_does(tmp_path: Path) -> None:
    assert digest_of(tmp_path, NEW) != digest_of(tmp_path, NEW + "- [ ] 3.1 Another task.\n")


def test_a_plan_recorded_from_the_old_spelling_is_current_for_the_rewritten_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": OLD})
    run.record("feature", sizing=cli.sizing_digest(), hash=recorded_before_the_tag_was_renamed(OLD))
    run.write("feature", NEW)

    assert not cli.has_work(run.inst, run.store)
    _, out = tick(run, capsys)

    assert run.calls == 0, out


def test_a_tick_after_tags_fix_makes_no_planner_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = ticking_replan(tmp_path, monkeypatch, {"feature": OLD})
    run.record("feature", sizing=cli.sizing_digest(), hash=recorded_before_the_tag_was_renamed(OLD))

    code, out = run_tags(capsys, "--fix", "feature")
    assert code == 0, out
    assert OLD_UNIT_TEST_TAG not in (run.inst.changes_dir / "feature" / "tasks.md").read_text()
    _, out = tick(run, capsys)

    assert run.calls == 0, out
