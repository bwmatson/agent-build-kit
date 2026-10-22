"""A run killed between the two empty commits of a recorded group resumes at that group's
implementation step, and a requeue after the pair-message stop resumes at its tests (spec:
built-group-recorded-as-empty-pair). The branch is real and starts with what the earlier run
left."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import FAILED
from tests.factories import git
from tests.graph.branch_fakes import (
    ACCOUNT,
    UNIT,
    messages,
    prepared,
    recorded_pair,
    subjects,
    titled,
)
from tests.graph.test_build_path import build
from tests.graph.test_per_group_build import group_named
from tests.runner_fakes import Killed

PAIR_3 = ["test: G3", "feat: G3"]


def leave_the_empty_test_commit(repo: Path) -> None:
    """What a run killed after recording `test: G4` left on the branch."""
    git(
        repo,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        f"test: G4\n\nUnit: {UNIT}\nAlready-built: yes\n",
    )


def test_a_unit_killed_after_the_empty_tests_commit_records_only_the_feat_commit(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(
        tmp_path,
        seeded=PAIR_3,
        groups={"add-marker": titled(3, 4)},
        meanwhile=leave_the_empty_test_commit,
        silent_groups=(4,),
        accounts={"4": ACCOUNT},
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert recorder.events[:3] == ["claude:impl", "commit:feat", "unit-test:whole_repo"]
    assert [group_named(prompt) for prompt in recorder.prompts[:1]] == ["4"]
    assert recorder.events.count("commit_built:feat") == 1
    assert "commit_built:test" not in recorder.events, "the empty tests commit is not made again"
    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"], "one pair for group 4"
    assert ACCOUNT in messages(repo)[-1]


def test_a_run_killed_between_the_empty_commits_ends_with_one_pair_for_group_4(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(
        tmp_path,
        groups={"add-marker": titled(3, 4)},
        silent_groups=(4,),
        kill_after="commit_built:test",
    )
    with pytest.raises(Killed):
        build(tmp_path, recorder, **recorder.overrides(tmp_path))
    assert subjects(repo) == [*PAIR_3, "test: G4"]

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    recorded_pair(repo)
    assert recorder.events.count("commit_built:test") == 1
    assert recorder.events.count("commit_built:feat") == 1


def test_a_requeue_after_the_pair_message_stop_on_a_unit_with_commits_resumes_at_group_4s_tests(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(
        tmp_path,
        seeded=PAIR_3,
        groups={"add-marker": titled(3, 4)},
        silent_groups=(4,),
    )
    recorder.store.set_state(
        UNIT, FAILED, note="the branch holds no tests and implementation pair for group 4 (G4)"
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert recorder.events[0] == "claude:tests", "resumed at group 4's tests"
    assert group_named(recorder.prompts[0]) == "4"
    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"]
