"""In a mode that writes tests, a tests node that ends with no test written, nothing said and no
`No-new-tests` marker runs once more with guidance and then fails naming the cause, before
`implement` runs; a `no_code` group runs no tests node (spec: group-build-modes, a tests step
that writes nothing stops early). The lone-`feat:` stop at `implement` stays the backstop,
pinned in `test_per_group_lone_feat_message.py`. The branch is real, and so is the tree digest
the node compares."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.wiring import build_tree_state
from tests.graph.branch_fakes import OnBranch, key, prepared, subjects
from tests.graph.branch_fakes import titled as groups_titled
from tests.graph.test_build_path import build

GROUPS = {"add-marker": groups_titled(1)}
CAUSE = "the tests step wrote no test"


class Refused(OnBranch):
    """A recorder over the real tree digest whose first `refused` tests calls write nothing and
    say nothing, as a refused write does."""

    def __init__(self, store: Any, *, refused: int, **options: Any) -> None:
        super().__init__(store, **options)
        self.refused = refused
        self.tests_calls = 0

    def tree_state(self, cwd: Path) -> str:
        return build_tree_state()(cwd)

    def claude(self, prompt: str, **kwargs: Any) -> str:
        answer = super().claude(prompt, **kwargs)
        if self.events[-1] != "claude:tests":
            return answer
        self.tests_calls += 1
        if self.tests_calls > self.refused:
            return answer
        (kwargs["cwd"] / f"work-{len(self.prompts)}.txt").unlink()
        return ""


def refusing(tmp_path: Path, refused: int, **options: Any) -> tuple[Refused, RunOutcome, Path]:
    recorder, repo = prepared(tmp_path, groups=GROUPS, **options)
    refusing_recorder = Refused(recorder.store, refused=refused)
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
    assert second != first, "the second try carries guidance"


def test_a_tests_node_that_writes_on_the_second_try_goes_on_to_implement(tmp_path: Path) -> None:
    recorder, outcome, repo = refusing(tmp_path, refused=1)

    assert outcome.status == "open", outcome.detail
    assert recorder.events.count("claude:tests") == 2
    assert subjects(repo) == ["test: G1", "feat: G1"]


def test_a_no_code_group_runs_no_tests_node(tmp_path: Path) -> None:
    recorder, outcome, _ = refusing(tmp_path, refused=2, modes={key(1): "no_code"})

    assert "claude:tests" not in recorder.events
    assert CAUSE not in outcome.detail
