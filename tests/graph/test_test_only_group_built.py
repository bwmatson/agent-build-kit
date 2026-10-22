"""A test-only group whose tests agent leaves nothing to commit is recorded with one empty,
marked `test:` commit when the whole repository's unit tests pass, and not otherwise (spec:
built-group-recorded-as-empty-pair). Each case that records nothing is built beside one that
does, so the file fails while nothing is recorded."""

from __future__ import annotations

from pathlib import Path

from tests.graph.branch_fakes import UNIT, built, files_in, messages, subjects, titled
from tests.graph.test_per_group_unstubbed import built as built_unstubbed

GROUPS = {"add-marker": titled(1, 2)}
STOPPED = "the branch holds no tests commit for group 2 (G2)"


def test_a_test_only_group_with_nothing_to_commit_and_passing_tests_is_recorded_empty(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, groups=GROUPS, e2e=(2,), silent_groups=(2,))

    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == ["test: G1", "feat: G1", "test: G2"], "no feat: for the group"
    message = messages(repo)[-1]
    assert f"Unit: {UNIT}" in message and "Already-built: yes" in message
    assert files_in(repo, "HEAD") == []
    assert recorder.events.count("unit-test:whole_repo") == 1
    assert recorder.events.count("claude:impl") == 1, "only group 1 has an implementation step"
    assert "review" in recorder.events, "the group counts as done and the unit goes to checks"


def test_the_same_group_with_failing_tests_records_nothing_and_stops(tmp_path: Path) -> None:
    passing, _, _ = built(tmp_path / "passing", groups=GROUPS, e2e=(2,), silent_groups=(2,))
    recorder, outcome, repo = built(
        tmp_path / "failing", groups=GROUPS, e2e=(2,), silent_groups=(2,), unit_test_ok=False
    )

    assert passing.events.count("unit-test:whole_repo") == 1
    assert outcome.status == "failed"
    assert STOPPED in outcome.detail
    assert subjects(repo) == ["test: G1", "feat: G1"]
    assert "review" not in recorder.events


def test_with_the_setting_off_no_empty_commit_is_made(tmp_path: Path) -> None:
    on, _, _ = built(tmp_path / "on", groups=GROUPS, e2e=(2,), silent_groups=(2,))
    off = built_unstubbed(tmp_path / "off", setting=False, profile="python-uv")

    assert on.events.count("commit_built:test") == 1
    assert not any("Already-built" in message for message in off.messages)
    assert "commit_built:test" not in off.events
