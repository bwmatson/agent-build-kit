"""A stubbed unit whose branch holds some commit of its own still needs a pair for every group,
and one with none is satisfied like an old build (spec: already-built-unit-satisfied). Each case
is built beside the one it is told from."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.units import SATISFIED
from tests.graph.branch_fakes import UNIT, built, subjects, titled

SILENT = {"silent_groups": (1, 2, 3)}
NOTE = "nothing to add and unit-test passes — satisfied"


def test_a_last_implementation_that_made_no_commit_still_stops_naming_group_3(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, no_commit_for="3")

    assert outcome.status == "failed"
    assert "the branch holds no tests and implementation pair for group 3" in outcome.detail
    assert "unit-test:whole_repo" not in recorder.events, "not sent as having produced nothing"
    assert recorder.store.get(UNIT).state != SATISFIED
    assert subjects(repo)[-1] == "test: G3"


def test_a_first_group_that_made_nothing_is_named_when_the_second_committed_a_pair(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, silent_groups=(1,))

    assert outcome.status == "failed"
    assert "pair for group 1" in outcome.detail
    assert "group 2" not in outcome.detail
    assert recorder.events.count("claude:tests") == 2, "stopped after the second group"
    assert subjects(repo) == ["test: G2", "feat: G2"]
    assert "unit-test:whole_repo" not in recorder.events


def test_a_tests_agent_that_leaves_uncommitted_files_has_them_committed_and_is_not_satisfied(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, groups={"add-marker": titled(1)}, no_commit_for="1")

    assert subjects(repo) == ["test: G1"], "the tests agent's files are committed"
    assert outcome.status == "failed"
    assert "pair for group 1" in outcome.detail
    assert recorder.store.get(UNIT).state != SATISFIED


def test_the_old_build_is_satisfied_by_a_zero_commit_branch_as_the_stubbed_one_is(
    tmp_path: Path,
) -> None:
    stubbed, stubbed_outcome, _ = built(tmp_path / "stubbed", **SILENT)
    old, old_outcome, repo = built(tmp_path / "old", setting=False, **SILENT)

    assert stubbed_outcome.status == old_outcome.status == "satisfied"
    assert stubbed.store.get(UNIT).state == old.store.get(UNIT).state == SATISFIED
    assert any(NOTE in line for line in stubbed.logged)
    assert any(NOTE in line for line in old.logged)
    assert subjects(repo) == []


def test_a_stubbed_and_an_old_build_over_one_zero_commit_branch_fail_alike(
    tmp_path: Path,
) -> None:
    stubbed, stubbed_outcome, _ = built(tmp_path / "stubbed", unit_test_ok=False, **SILENT)
    old, old_outcome, _ = built(tmp_path / "old", setting=False, unit_test_ok=False, **SILENT)

    assert stubbed_outcome.status == old_outcome.status == "failed"
    assert stubbed.store.get(UNIT).state == old.store.get(UNIT).state
    assert "unit-test failed" in stubbed_outcome.detail
    assert "unit-test failed" in old_outcome.detail
