"""A run killed after the empty `test:` of a group with no new tests resumes at that group's
implementation step, and one killed before it runs the group's checks again and makes it (spec:
built-group-recorded-as-empty-pair). The branch is real and the second run starts with what
the first left."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.graph.branch_fakes import files_in, prepared, recorded_pair, subjects, titled
from tests.graph.test_build_path import build
from tests.graph.test_per_group_build import group_named
from tests.runner_fakes import Killed

GROUPS = {"add-marker": titled(3, 4)}
PAIR_3 = ["test: G3", "feat: G3"]


def test_a_run_killed_after_the_empty_test_commit_resumes_at_the_implementation_and_changes_a_file(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(tmp_path, groups=GROUPS, no_tests_for="4", kill_in_impl="4")
    with pytest.raises(Killed):
        build(tmp_path, recorder, **recorder.overrides(tmp_path))
    assert subjects(repo) == [*PAIR_3, "test: G4"], "the empty test: is on the branch"
    seen, asked = len(recorder.events), len(recorder.prompts)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert recorder.events[seen] == "claude:impl", "resumed at implement, the tests step skipped"
    assert group_named(recorder.prompts[asked]) == "4"
    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"], "one pair for group 4"
    assert files_in(repo, "HEAD") != []
    assert recorder.events.count("commit_built:test") == 1


def test_a_run_killed_after_the_empty_test_commit_resumes_and_an_unchanged_tree_ends_in_a_pair(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(tmp_path, groups=GROUPS, silent_groups=(4,), kill_in_impl="4")
    with pytest.raises(Killed):
        build(tmp_path, recorder, **recorder.overrides(tmp_path))
    seen = len(recorder.events)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert recorder.events[seen] == "claude:impl"
    recorded_pair(repo)
    assert recorder.events.count("unit-test:whole_repo") == 1


def test_a_run_killed_before_the_empty_test_commit_runs_the_checks_again_and_makes_it(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(
        tmp_path,
        seeded=PAIR_3,
        groups=GROUPS,
        no_tests_for="4",
        kill_after="commit:test",
    )
    with pytest.raises(Killed):
        build(tmp_path, recorder, **recorder.overrides(tmp_path))
    assert subjects(repo) == PAIR_3
    seen = len(recorder.events)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert "stub-checks" in recorder.events[seen:], "the static checks run again before the commit"
    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"]
    assert recorder.events.count("commit_built:test") == 1
