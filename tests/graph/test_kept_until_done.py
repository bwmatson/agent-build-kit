"""What a run could not post or close is kept on the unit instead of being dropped."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.units import IN_REVIEW, branch_name
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import empty_branch, fresh, tasks_file
from tests.graph_driver import position


def test_a_reply_the_host_did_not_take_stays_in_the_pending_list_for_the_next_pass(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "[comment 11] a.py:3 — rename", from_person=True)
    owed = json.dumps(dict(replies=[dict(comment_id="11", body="done")]))

    build(tmp_path, recorder, reply=lambda **kwargs: owed)

    after = position(tmp_path).state
    assert after is not None
    assert after.pending_replies == (owed,)


def test_a_close_that_failed_is_kept_as_pending_on_the_unit(tmp_path: Path) -> None:
    tasks_file(tmp_path)
    recorder = fresh(tmp_path, commits_from_impl=0, close_error="502 Bad Gateway")
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))

    build(tmp_path, recorder, graph=[recorder.store.get(unit().id)], **empty_branch())

    pending = recorder.store.get(unit().id).close_pending
    assert pending is not None and pending.pr == 4
    assert "Task group(s) 1" in pending.reason
