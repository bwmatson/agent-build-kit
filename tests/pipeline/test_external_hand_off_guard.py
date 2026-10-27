"""A hold is refused on started work, with guidance (spec: external-work)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.external_file import HoldRefused, check_not_started
from tests.external_support import change_with, hold
from tests.factories import stored_unit


def test_a_hold_on_a_group_of_a_running_unit_is_refused_naming_unit_state_and_guidance(
    tmp_path: Path,
) -> None:
    folder = change_with(tmp_path)
    running = stored_unit("feature/1", change="feature", state="running", branch="spec/feature/1")

    with pytest.raises(HoldRefused) as refused:
        check_not_started(folder, hold((1,)), [running])

    message = str(refused.value)
    assert "feature/1" in message and "running" in message
    assert "finish" in message and "retire" in message


def test_a_hold_on_a_planned_unit_with_a_pushed_commit_is_refused_as_worked_on(
    tmp_path: Path,
) -> None:
    folder = change_with(tmp_path)
    pushed = stored_unit("feature/2", change="feature", branch="spec/feature/2", pushed="0123abc")

    with pytest.raises(HoldRefused) as refused:
        check_not_started(folder, hold((2,)), [pushed])

    message = str(refused.value)
    assert "feature/2" in message and "planned" in message
    assert "finish" in message and "retire" in message


def test_a_hold_with_the_all_scope_is_refused_for_any_started_group(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    reviewing = stored_unit("feature/3", change="feature", state="in_review", pr=7)

    with pytest.raises(HoldRefused, match=r"feature/3"):
        check_not_started(folder, hold("all"), [reviewing])


def test_a_planned_unit_with_no_work_is_accepted_and_a_started_one_beside_it_is_not(
    tmp_path: Path,
) -> None:
    folder = change_with(tmp_path)
    untouched = stored_unit("feature/1", change="feature")
    started = stored_unit("feature/2", change="feature", branch="spec/feature/2")

    check_not_started(folder, hold((1,)), [untouched, started])

    with pytest.raises(HoldRefused, match=r"feature/2"):
        check_not_started(folder, hold((2,)), [untouched, started])


def test_a_retired_or_superseded_unit_does_not_stop_a_hold_on_its_groups(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    retired = stored_unit(
        "feature/1", change="feature", state="retired", branch="spec/feature/1", pr=4
    )
    unplanned = stored_unit("feature/2", change="feature", state="unplanned")
    replaced = stored_unit(
        "feature/3",
        change="feature",
        state="closed",
        branch="spec/feature/3",
        pr=5,
        superseded_by=("feature/3-s1",),
    )

    check_not_started(folder, hold("all"), [retired, unplanned, replaced])
