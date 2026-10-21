"""A stubbed unit with no commit of its own is built again from its first group when it is
requeued, and ends satisfied (spec: already-built-unit-satisfied)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.units import FAILED
from tests.graph.branch_fakes import UNIT, agent_calls, built, prepared, subjects, titled
from tests.graph.test_build_path import build
from tests.graph.test_per_group_build import group_named


def test_a_unit_stopped_with_the_pair_message_and_requeued_with_no_commit_ends_satisfied(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(tmp_path, silent_groups=(1, 2, 3))
    recorder.store.set_state(
        UNIT, FAILED, note="the branch holds no tests and implementation pair for group 1 (G1)"
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "satisfied", outcome.detail
    assert recorder.events[0] == "claude:tests", "resumed at the tests, existing == 0"
    assert [group_named(prompt) for prompt in recorder.prompts[:2]] == ["1", "1"]
    assert agent_calls(recorder.events) == ["claude:tests", "claude:impl"] * 3
    assert subjects(repo) == []


def test_a_unit_of_only_test_only_groups_whose_tests_agent_wrote_nothing_ends_satisfied(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(
        tmp_path, groups={"add-marker": titled(1, 2)}, e2e=(1, 2), silent_groups=(1, 2)
    )

    assert outcome.status == "satisfied", outcome.detail
    assert agent_calls(recorder.events) == ["claude:tests"] * 2, "no implementation is asked for"
    assert recorder.events.count("unit-test:whole_repo") == 1
    assert "review" not in recorder.events
    assert subjects(repo) == []
