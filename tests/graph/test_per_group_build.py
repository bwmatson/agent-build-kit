"""A stubbed build writes a tests and an implementation commit for each task group, in order
(spec: per-group-commits)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.graph.stub_loop_fakes import stubbed_build, with_three_groups
from tests.graph.test_build_path import build
from tests.graph.test_joined_unit_builds import tasks

STEPS = {"claude:tests", "stub-checks", "commit:test", "claude:impl", "commit:feat"}


def group_named(prompt: str) -> str:
    """The task group numbers a build prompt names."""
    found = re.search(r"task group\(s\) (\d+(?:, \d+)*)", prompt)
    assert found, prompt
    return found.group(1)


def test_the_agent_is_called_for_each_groups_tests_then_its_implementation_in_order(
    tmp_path: Path,
) -> None:
    stubbed_build()
    tasks(tmp_path, "add-marker", (1, 2, 3))
    recorder = with_three_groups(tmp_path)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open"
    built = [event for event in recorder.events if event in STEPS]
    assert (
        built[: 5 * 3]
        == [
            "claude:tests",
            "stub-checks",
            "commit:test",
            "claude:impl",
            "commit:feat",
        ]
        * 3
    )
    assert [group_named(prompt) for prompt in recorder.prompts[:6]] == [
        "1",
        "1",
        "2",
        "2",
        "3",
        "3",
    ], "each prompt names only its own group"


def test_the_branch_holds_a_pair_of_commits_titled_with_each_group(tmp_path: Path) -> None:
    stubbed_build()
    tasks(tmp_path, "add-marker", (1, 2, 3))
    recorder = with_three_groups(tmp_path)

    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert recorder.subjects == [
        "test: G1",
        "feat: G1",
        "test: G2",
        "feat: G2",
        "test: G3",
        "feat: G3",
    ]


def test_the_checks_and_review_come_after_the_last_group(tmp_path: Path) -> None:
    stubbed_build()
    tasks(tmp_path, "add-marker", (1, 2, 3))
    recorder = with_three_groups(tmp_path)

    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert recorder.events.count("commit:feat") == 3
    last_commit = len(recorder.events) - 1 - recorder.events[::-1].index("commit:feat")
    assert recorder.events.count("unit-test") == 1
    assert recorder.events.index("unit-test") > last_commit
    assert recorder.events.index("review") > recorder.events.index("unit-test")
