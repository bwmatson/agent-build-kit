"""A stubbed build takes the group it is on from the branch, where a test-only group is done
once its `test:` commit is there (spec: test-only-groups)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.graph.branch_fakes import agent_calls, built, prepared, subjects, titled
from tests.graph.test_build_path import build, limited
from tests.graph.test_per_group_build import group_named
from tests.graph.test_per_group_resume import rewrite_every_hash
from tests.runner_fakes import Killed

TWO = titled(1, 2)
SAME = {1: ("Wire it", ""), 2: ("Wire it", "")}
PAIR = ["test: G1", "feat: G1"]


def test_a_branch_holding_the_pair_and_the_test_only_commit_resumes_at_the_checks(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(
        tmp_path, groups={"add-marker": TWO}, e2e=(2,), seeded=[*PAIR, "test: G2"]
    )

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == [], "nothing is written"
    assert recorder.subjects == []
    assert "unit-test" in recorder.events and "review" in recorder.events
    assert subjects(repo) == [*PAIR, "test: G2"]


def test_a_branch_holding_only_the_first_pair_resumes_at_the_test_only_groups_tests(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, groups={"add-marker": TWO}, e2e=(2,), seeded=PAIR)

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == ["claude:tests"], "tests, and no implementation"
    assert group_named(recorder.prompts[0]) == "2"
    assert subjects(repo) == [*PAIR, "test: G2"]


def test_a_run_killed_in_the_test_only_groups_stub_loop_resumes_at_the_fix(
    tmp_path: Path,
) -> None:
    limited(max_check_rounds=2)
    recorder, repo = prepared(
        tmp_path,
        groups={"add-marker": {1: ("G1", "")}},
        e2e=(1,),
        checks=[(False, "STUB-OUTPUT-0"), (False, "STUB-OUTPUT-1"), (True, "")],
        kill_in_fix=2,
    )

    with pytest.raises(Killed):
        build(tmp_path, recorder, **recorder.overrides(tmp_path))
    killed_at = len(recorder.events)
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    resumed = recorder.events[killed_at:]
    assert resumed[0] == "claude:fix_stub", "back in the fix, not in the tests"
    assert resumed.count("claude:fix_stub") == 1, "the first fix is counted, so one is left"
    assert recorder.events.count("claude:tests") == 1
    assert outcome.status == "open", outcome.detail
    assert "claude:impl" not in recorder.events
    assert subjects(repo) == ["test: G1"]


def test_a_restack_that_rewrote_every_hash_resumes_the_same(tmp_path: Path) -> None:
    recorder, outcome, repo = built(
        tmp_path,
        groups={"add-marker": TWO},
        e2e=(2,),
        seeded=[*PAIR, "test: G2"],
        meanwhile=rewrite_every_hash,
    )

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == []
    assert subjects(repo) == [*PAIR, "test: G2"]


def test_two_groups_with_one_title_are_told_apart_by_position(tmp_path: Path) -> None:
    recorder, outcome, repo = built(
        tmp_path,
        groups={"add-marker": SAME},
        e2e=(2,),
        seeded=["test: Wire it", "feat: Wire it"],
    )

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == ["claude:tests"]
    assert group_named(recorder.prompts[0]) == "2"
    assert subjects(repo) == ["test: Wire it", "feat: Wire it", "test: Wire it"]
