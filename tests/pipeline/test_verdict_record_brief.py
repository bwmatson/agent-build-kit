"""A verdict record says whether its pull request carried the brief (spec: review-brief)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.verdict_record import VERDICTS, mark_brief
from tests.factories import activate_with
from tests.graph.test_build_path import build, fresh
from tests.runner_fakes import Recorder, approving

UNIT_ID = "add-marker/1"


def brief_of(tmp_path: Path) -> bool:
    return json.loads((tmp_path / VERDICTS).read_text())[UNIT_ID]["brief"]


def built(tmp_path: Path, **review: Any) -> Recorder:
    activate_with(review={"enabled": True, **review})
    recorder = fresh(tmp_path)
    recorder.verdicts = [approving()]
    build(tmp_path, recorder)
    return recorder


def test_opening_a_body_with_the_section_sets_brief_true(tmp_path: Path) -> None:
    recorder = built(tmp_path, brief=True)

    assert "## Start here" in recorder.bodies[0]
    assert brief_of(tmp_path) is True


def test_updating_the_body_after_a_later_approval_sets_brief_true_again(tmp_path: Path) -> None:
    recorder = built(tmp_path, brief=True)
    recorder.store.set_feedback(UNIT_ID, "[comment 11] a.py:3 — rename", from_person=True)
    recorder.verdicts = [approving()]

    build(tmp_path, recorder)

    assert recorder.pr_calls == 2
    assert brief_of(tmp_path) is True


def test_a_body_without_the_section_leaves_brief_false(tmp_path: Path) -> None:
    recorder = built(tmp_path, brief=False)

    assert "## Start here" not in recorder.bodies[0]
    assert brief_of(tmp_path) is False


def test_a_unit_with_no_record_is_left_with_none_and_logs_no_failure(tmp_path: Path) -> None:
    path = tmp_path / VERDICTS

    mark_brief(path, UNIT_ID)
    assert not path.exists()

    other = json.dumps({"other/1": {"brief": False}})
    path.write_text(other)
    mark_brief(path, UNIT_ID)
    assert path.read_text() == other


def test_opening_a_pr_for_a_unit_with_no_record_logs_nothing_of_the_verdict(
    tmp_path: Path,
) -> None:
    activate_with(review={"enabled": True, "brief": True})
    recorder = fresh(tmp_path)
    recorder.verdicts = [approving()]
    push = recorder.push

    def push_then_forget(branch: str, *, cwd: Path) -> str:
        sha = push(branch, cwd=cwd)
        (tmp_path / VERDICTS).unlink(missing_ok=True)
        return sha

    build(tmp_path, recorder, push=push_then_forget)

    assert recorder.pr_calls == 1
    assert not (tmp_path / VERDICTS).exists()
    assert not [line for line in recorder.logged if "verdict" in line.lower()]


def test_a_state_directory_that_refuses_the_write_is_logged_and_the_pr_is_still_opened(
    tmp_path: Path,
) -> None:
    activate_with(review={"enabled": True, "brief": True})
    recorder = fresh(tmp_path)
    recorder.verdicts = [approving()]
    push = recorder.push
    lock = tmp_path / (VERDICTS + ".lock")

    def push_then_refuse(branch: str, *, cwd: Path) -> str:
        sha = push(branch, cwd=cwd)
        # The record's lock can no longer be taken, whoever runs the test.
        lock.unlink(missing_ok=True)
        lock.mkdir()
        return sha

    build(tmp_path, recorder, push=push_then_refuse)

    assert recorder.pr_calls == 1
    assert "## Start here" in recorder.bodies[0]
    assert [line for line in recorder.logged if "verdict" in line.lower()]
    assert brief_of(tmp_path) is False
