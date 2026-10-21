"""After the last group a stubbed build counts the groups the branch satisfies: a pair, or a
test-only group's lone tests commit (spec: test-only-groups). Each case is built beside the one
it is told from."""

from __future__ import annotations

from pathlib import Path

from tests.graph.branch_fakes import built, subjects

TWO = {1: ("Parse the key", ""), 2: ("Drive the stack", "")}
THREE = {1: ("G1", ""), 2: ("G2", ""), 3: ("G3", "")}
STOPPED = "the branch holds no tests and implementation pair for group 2 (Drive the stack)"


def test_a_full_count_with_a_test_only_last_group_goes_on_and_an_ordinary_one_stops(
    tmp_path: Path,
) -> None:
    only, outcome, repo = built(tmp_path / "only", groups={"add-marker": TWO}, e2e=(2,))
    ordinary, stopped, _ = built(
        tmp_path / "ordinary", groups={"add-marker": TWO}, no_commit_for="2"
    )

    assert outcome.status == "open"
    assert len(subjects(repo)) == 3 and "review" in only.events
    assert stopped.status == "failed"
    assert STOPPED in stopped.detail
    assert "review" not in ordinary.events


def test_a_unit_test_group_holding_only_tests_still_needs_its_implementation_commit(
    tmp_path: Path,
) -> None:
    ordinary, stopped, repo = built(
        tmp_path / "ordinary", groups={"add-marker": TWO}, tests_only=(2,), no_commit_for="2"
    )
    _, outcome, _ = built(
        tmp_path / "e2e", groups={"add-marker": TWO}, e2e=(2,), tests_only=(2,), no_commit_for="2"
    )

    assert stopped.status == "failed"
    assert STOPPED in stopped.detail
    assert subjects(repo)[-1] == "test: Drive the stack"
    assert "review" not in ordinary.events
    assert outcome.status == "open", "the same branch, headed [e2e-test], is satisfied"


def test_a_short_count_with_a_test_only_last_group_names_the_earlier_group(
    tmp_path: Path,
) -> None:
    recorder, outcome, _ = built(
        tmp_path,
        groups={"add-marker": THREE},
        e2e=(2, 3),
        seeded=["test: G1", "feat: G1", "test: G3"],
    )

    assert outcome.status == "failed"
    assert "group 2 (G2)" in outcome.detail
    assert "claude:impl" not in recorder.events, "no group here has an implementation step"
    assert "review" not in recorder.events
