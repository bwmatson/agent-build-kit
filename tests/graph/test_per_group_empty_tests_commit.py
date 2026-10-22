"""A group of a unit with commits whose tests step commits nothing gets an empty `test:` marked
`Already-built: yes` at the end of that step, and its implementation completes the pair, with a
real `feat:` or with an empty one once the whole repository's unit tests pass (spec:
built-group-recorded-as-empty-pair). The branch is real."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import FeedbackSource
from agent_build_kit.pipeline.units import FAILED
from tests.graph.branch_fakes import (
    ACCOUNT,
    TRAILER,
    UNIT,
    built,
    files_in,
    messages,
    prepared,
    recorded_pair,
    subjects,
    titled,
)
from tests.graph.test_build_path import build
from tests.graph.test_per_group_build import group_named

GROUPS = {"add-marker": titled(3, 4)}
PAIR_3 = ["test: G3", "feat: G3"]
PAIR = "the branch holds no tests and implementation pair for group 4 (G4)"


def test_a_group_with_no_new_tests_gets_an_empty_marked_test_commit_before_its_implementation(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, groups=GROUPS, no_tests_for="4")

    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"]
    assert files_in(repo, "HEAD~1") == [], "the tests commit holds no file"
    assert files_in(repo, "HEAD") != [], "the implementation commit holds the agent's file"
    tests_commit, feat_commit = messages(repo)[-2:]
    assert tests_commit.splitlines()[-2:] == [TRAILER, "Already-built: yes"]
    assert "adds no new tests" in tests_commit
    assert "Already-built" not in feat_commit
    assert "unit-test:whole_repo" not in recorder.events
    for step in ("unit-test", "review"):
        assert step in recorder.events, "the unit goes on to the checks and the review"
    implementations = [found for step, found in recorder.at_agent if step == "claude:impl"]
    assert implementations[-1] == [*PAIR_3, "test: G4"], "the empty test: precedes the agent"


def test_an_implementation_that_changes_nothing_completes_the_pair_with_an_empty_feat_commit(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(
        tmp_path, groups=GROUPS, silent_groups=(4,), accounts={"4": ACCOUNT}
    )

    assert outcome.status == "open", outcome.detail
    recorded_pair(repo)
    assert ACCOUNT in messages(repo)[-1]
    assert recorder.events.count("unit-test:whole_repo") == 1


def test_failing_unit_tests_leave_the_empty_test_commit_and_make_no_feat_commit_until_a_requeue(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(tmp_path, groups=GROUPS, silent_groups=(4,), unit_test_ok=False)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert PAIR in outcome.detail
    assert subjects(repo) == [*PAIR_3, "test: G4"]
    assert "Already-built: yes" in messages(repo)[-1]
    assert recorder.events.count("unit-test:whole_repo") == 1
    assert recorder.store.get(UNIT).feedback_source == FeedbackSource.UNIT_TEST

    recorder.unit_test_ok = True
    recorder.store.set_state(UNIT, FAILED, note=PAIR)
    seen, asked = len(recorder.events), len(recorder.prompts)
    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert recorder.events[seen] == "claude:impl", "resumed at group 4's implementation"
    assert group_named(recorder.prompts[asked]) == "4"
    recorded_pair(repo)
