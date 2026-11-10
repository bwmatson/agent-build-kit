"""In a mode that writes tests, a tests node that ends with no test written, nothing said and no
`No-new-tests` marker runs once more with guidance and then fails naming the cause, before
`implement` runs; a `no_code` group runs no tests node (spec: group-build-modes, a tests step
that writes nothing stops early). The lone-`feat:` stop at `implement` stays the backstop,
pinned in `test_per_group_lone_feat_message.py`. The branch is real, and so is the tree digest
the node compares."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_build_kit.graph.nodes import NO_NEW_TESTS, WROTE_NOTHING_NOTE
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.wiring import build_tree_state
from tests.graph.branch_fakes import (
    ACCOUNT,
    Groups,
    OnBranch,
    key,
    messages,
    prepared,
    subjects,
    titled,
)
from tests.graph.test_build_path import build
from tests.graph.test_per_group_build import group_named
from tests.graph.test_per_group_lone_feat_message import marked_empty

GROUPS = {"add-marker": titled(1)}
LONE_GROUPS = {"add-marker": titled(3, 4)}
LONE_SEEDED = ["test: G3", "feat: G3", "feat: G4"]
CAUSE = "the tests step wrote no test"
CLAIM = "Added four tests to tests/graph and they all fail as they should"
UNCHANGED = "tree is unchanged"


class Refused(OnBranch):
    """A recorder over the real tree digest whose first `refused` tests calls write nothing and
    say `said` (nothing by default), as a refused write does."""

    def __init__(
        self, store: Any, *, refused: int, group: str = "", said: str = "", **options: Any
    ) -> None:
        super().__init__(store, **options)
        self.refused = refused
        self.said = said
        self.group = group  # as the prompt names it; every group when empty
        self.tests_calls = 0

    def tree_state(self, cwd: Path) -> str:
        return build_tree_state()(cwd)

    def claude(self, prompt: str, **kwargs: Any) -> str:
        answer = super().claude(prompt, **kwargs)
        if self.events[-1] != "claude:tests" or self.group not in ("", group_named(prompt)):
            return answer
        self.tests_calls += 1
        if self.tests_calls > self.refused:
            return answer
        (kwargs["cwd"] / f"work-{len(self.prompts)}.txt").unlink()
        return self.said


def refusing(
    tmp_path: Path,
    refused: int,
    *,
    group: str = "",
    said: str = "",
    groups: Mapping[str, Groups] = GROUPS,
    **options: Any,
) -> tuple[Refused, RunOutcome, Path]:
    recorder, repo = prepared(tmp_path, groups=groups, **options)
    refusing_recorder = Refused(recorder.store, refused=refused, group=group, said=said)
    outcome = build(tmp_path, refusing_recorder, **refusing_recorder.overrides(tmp_path))
    return refusing_recorder, outcome, repo


def test_a_tests_node_that_writes_nothing_runs_once_more_then_fails_before_implement(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = refusing(tmp_path, refused=2)

    assert outcome.status == "failed", outcome.detail
    assert CAUSE in outcome.detail
    assert recorder.events.count("claude:tests") == 2, "one more try, no more"
    assert "claude:impl" not in recorder.events
    assert subjects(repo) == []
    first, second = recorder.prompts[:2]  # the build's first agent calls are its tests step's
    assert WROTE_NOTHING_NOTE in second
    assert WROTE_NOTHING_NOTE not in first


def test_a_later_group_whose_tests_node_writes_nothing_fails_without_an_empty_test_commit(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = refusing(
        tmp_path, refused=2, group="4", groups={"add-marker": titled(3, 4)}
    )

    assert outcome.status == "failed", outcome.detail
    assert CAUSE in outcome.detail
    assert subjects(repo) == ["test: G3", "feat: G3"], "no test: G4, empty or not"
    assert recorder.events.count("claude:impl") == 1, "only group 3's implementation ran"


def test_a_tests_node_that_writes_on_the_second_try_goes_on_to_implement(tmp_path: Path) -> None:
    recorder, outcome, repo = refusing(tmp_path, refused=1)

    assert outcome.status == "open", outcome.detail
    assert recorder.events.count("claude:tests") == 2
    assert subjects(repo) == ["test: G1", "feat: G1"]


def test_a_no_code_group_runs_no_tests_node(tmp_path: Path) -> None:
    recorder, outcome, _ = refusing(tmp_path, refused=2, modes={key(1): "no_code"})

    assert "claude:tests" not in recorder.events
    assert CAUSE not in outcome.detail


def test_a_tests_required_group_whose_tree_is_unchanged_is_run_once_more_whatever_was_said(
    tmp_path: Path,
) -> None:
    recorder, _, _ = refusing(tmp_path, refused=1, said=CLAIM, tests_required=(1,))

    assert recorder.events.count("claude:tests") == 2
    first, second = recorder.prompts[:2]
    assert UNCHANGED in second
    assert UNCHANGED not in first


def test_a_tests_required_group_unchanged_twice_stops_before_the_stub_checks_quoting_the_agent(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = refusing(tmp_path, refused=2, said=CLAIM, tests_required=(1,))

    assert outcome.status == "failed", outcome.detail
    assert CAUSE in outcome.detail
    assert CLAIM in outcome.detail
    assert recorder.events.count("claude:tests") == 2, "one more try, no more"
    assert "stub-checks" not in recorder.events
    assert "claude:impl" not in recorder.events
    assert subjects(repo) == []


def test_a_tests_required_group_that_writes_on_the_second_run_goes_on_to_the_checks(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = refusing(tmp_path, refused=1, said=CLAIM, tests_required=(1,))

    assert outcome.status == "open", outcome.detail
    assert recorder.events.index("stub-checks") < recorder.events.index("claude:impl")
    assert subjects(repo) == ["test: G1", "feat: G1"]


def test_a_first_group_without_required_tests_that_says_they_exist_is_recorded_as_empty_pair(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = refusing(tmp_path, refused=1, said=ACCOUNT)

    assert outcome.status == "open", outcome.detail
    assert recorder.events.count("claude:tests") == 1, "an explanation is a judgment: no retry"
    assert subjects(repo) == ["test: G1", "feat: G1"]
    assert NO_NEW_TESTS in messages(repo)[0]


def test_implement_does_not_start_for_a_group_with_no_tests_commit(tmp_path: Path) -> None:
    """A lone `feat:` keeps the empty marked `test:` from being recorded, so the route into
    implement finds no `test:` commit for the group."""
    recorder, repo = prepared(
        tmp_path, groups=LONE_GROUPS, seeded=LONE_SEEDED, silent_groups=(4,), meanwhile=marked_empty
    )
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed", outcome.detail
    assert "tests step" in outcome.detail
    assert "claude:impl" not in recorder.events
