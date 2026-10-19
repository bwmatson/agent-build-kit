"""Two groups with the same title are told apart by their position in the unit, not by the title
on the branch (spec: per-group-commits)."""

from __future__ import annotations

from pathlib import Path

from tests.graph.branch_fakes import built, subjects
from tests.graph.test_per_group_build import group_named

SAME = {1: ("Wire it", ""), 2: ("Wire it", "")}


def test_a_branch_holding_the_first_groups_pair_resumes_at_the_second(tmp_path: Path) -> None:
    recorder, outcome, repo = built(
        tmp_path, groups={"add-marker": SAME}, seeded=["test: Wire it", "feat: Wire it"]
    )

    assert outcome.status == "open"
    assert [group_named(prompt) for prompt in recorder.prompts[:2]] == ["2", "2"]
    assert recorder.subjects == ["test: Wire it", "feat: Wire it"]
    assert subjects(repo) == ["test: Wire it", "feat: Wire it"] * 2


def test_a_branch_holding_the_first_groups_tests_resumes_at_its_implementation(
    tmp_path: Path,
) -> None:
    recorder, _, repo = built(tmp_path, groups={"add-marker": SAME}, seeded=["test: Wire it"])

    assert recorder.events[0] == "claude:impl"
    assert [group_named(prompt) for prompt in recorder.prompts[:3]] == ["1", "2", "2"]
    assert subjects(repo) == ["test: Wire it", "feat: Wire it"] * 2
