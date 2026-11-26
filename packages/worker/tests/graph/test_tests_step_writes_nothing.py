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

import pytest

from agent_build_kit.graph.nodes import (
    NO_NEW_TESTS,
    NO_TESTS_COMMIT,
    UNCHANGED_TREE_NOTE,
    WROTE_NOTHING_NOTE,
)
from agent_build_kit.pipeline.shell import porcelain
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.wiring import build_tree_state
from agent_build_kit.pipeline.workspaces import DirtyWorktree
from agent_build_kit.runtimes import AgentResult, RefusedCall
from packages.worker.tests.graph.test_build_path import build
from packages.worker.tests.graph.test_per_group_build import group_named
from packages.worker.tests.graph.test_per_group_lone_feat_message import marked_empty
from packages.worker.tests.graph.test_red_check_in_build import RedAnswers
from tests.graph.branch_fakes import (
    ACCOUNT,
    Groups,
    OnBranch,
    files_in,
    key,
    messages,
    prepared,
    subjects,
    titled,
)
from tests.runner_fakes import Killed

GROUPS = {"add-marker": titled(1)}
LONE_GROUPS = {"add-marker": titled(3, 4)}
LONE_SEEDED = ["test: G3", "feat: G3", "feat: G4"]
CAUSE = "the tests step wrote no test"
CLAIM = "Added four tests to tests/graph and they all fail as they should"
UNCHANGED = "tree is unchanged"
COMMAND = 'echo "$X" >> tests/test_a.py'
REASON = "A variable in this command can't be checked before it runs"
REFUSED = (RefusedCall(tool="Bash", subject=COMMAND, reason=REASON),)
DID_NOT_RUN = "did not run"


class Refused(OnBranch):
    """A recorder over the real tree digest whose first `refused` tests calls write nothing and
    say `said` (nothing by default), as a refused write does."""

    def __init__(
        self,
        store: Any,
        *,
        refused: int,
        group: str = "",
        said: str = "",
        refused_calls: tuple[RefusedCall, ...] = (),
        **options: Any,
    ) -> None:
        super().__init__(store, **options)
        self.refused = refused
        self.said = said
        self.refused_calls = refused_calls  # what the permission layer refused in those runs
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
        if kwargs.get("on_result") and self.refused_calls:
            result = AgentResult(ok=True, text=self.said, refused_calls=self.refused_calls)
            kwargs["on_result"](result, role="implement", model="m", runtime="fake")
        return self.said


def refusing(
    tmp_path: Path,
    refused: int,
    *,
    group: str = "",
    said: str = "",
    groups: Mapping[str, Groups] = GROUPS,
    refused_calls: tuple[RefusedCall, ...] = (),
    **options: Any,
) -> tuple[Refused, RunOutcome, Path]:
    recorder, repo = prepared(tmp_path, groups=groups, **options)
    refusing_recorder = Refused(
        recorder.store, refused=refused, group=group, said=said, refused_calls=refused_calls
    )
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


@pytest.mark.parametrize(
    "options",
    [
        pytest.param({}, id="tests-optional"),
        pytest.param({"said": CLAIM, "tests_required": (1,)}, id="tests-required"),
    ],
)
def test_a_retry_after_a_refused_call_names_the_call_and_says_it_did_not_run(
    tmp_path: Path, options: dict[str, Any]
) -> None:
    recorder, _, _ = refusing(tmp_path, refused=1, refused_calls=REFUSED, **options)

    first, second = recorder.prompts[:2]
    note = second.removesuffix(
        first
    )  # the first prompt itself also says a refused call did not run
    assert note != second
    assert f"{REFUSED[0].tool}: `{COMMAND}`" in note
    assert REASON in note
    assert DID_NOT_RUN in note
    assert (UNCHANGED_TREE_NOTE if "tests_required" in options else WROTE_NOTHING_NOTE) in note
    assert COMMAND not in first


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


def test_a_first_group_that_says_its_tests_exist_gets_an_empty_marked_test_before_its_feat(
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
        tmp_path,
        groups=LONE_GROUPS,
        seeded=LONE_SEEDED,
        silent_groups=(4,),
        meanwhile=marked_empty,
        asked=True,
    )
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed", outcome.detail
    assert NO_TESTS_COMMIT in outcome.detail
    assert "claude:impl" not in recorder.events


TEST_FILE = "tests/test_marker.py"
CODE_FILE = "src/marker.py"
TEST_TEXT = "def test_a() -> None: ...\n"
CODE_TEXT = "def mark() -> None: ...\n"
DOC_FILE = "docs/marker.md"
DOC_TEXT = "# Marker\n"


class KilledInTests(OnBranch):
    """A recorder whose first tests call leaves `leftovers` (path to text) uncommitted in the tree
    and dies; every tests call after it writes nothing, as an agent that keeps what it finds."""

    def __init__(self, store: Any, *, leftovers: Mapping[str, str], **options: Any) -> None:
        super().__init__(store, no_tests_for="1", **options)
        self.leftovers = leftovers
        self.killed = False

    def tree_state(self, cwd: Path) -> str:
        return build_tree_state()(cwd)

    def claude(self, prompt: str, **kwargs: Any) -> str:
        answer = super().claude(prompt, **kwargs)
        if self.events[-1] == "claude:tests" and not self.killed:
            self.killed = True
            for name, text in self.leftovers.items():
                (kwargs["cwd"] / name).parent.mkdir(parents=True, exist_ok=True)
                (kwargs["cwd"] / name).write_text(text)
            raise Killed("claude:tests")
        return answer


def resumed_over(
    tmp_path: Path,
    leftovers: Mapping[str, str],
    *,
    said: str = "",
    red_answers: list[tuple[bool, str]] | None = None,
) -> tuple[KilledInTests, RunOutcome, Path]:
    """A `Tests: required` group whose tests step died leaving `leftovers` in the tree, then
    resumed over them by an agent that writes nothing more and says `said`. The worktree refuses
    a dirty tree unless allowed, as the real one."""
    base, repo = prepared(tmp_path, groups=GROUPS, tests_required=(1,))
    recorder = KilledInTests(
        base.store, leftovers=leftovers, tests_accounts={"1": said} if said else None
    )

    def worktree(unit: Any, branch: str, allow_dirty: bool = False) -> Path:
        status = porcelain(repo)
        if status and not allow_dirty:
            raise DirtyWorktree("uncommitted changes", paths=tuple(name for _, name in status))
        return repo

    options: dict[str, Any] = {**recorder.overrides(tmp_path), "worktree": worktree}
    if red_answers is not None:
        options["run_red_check"] = RedAnswers(recorder, red_answers)
    with pytest.raises(Killed):
        build(tmp_path, recorder, **options)
    return recorder, build(tmp_path, recorder, **options), repo


@pytest.mark.parametrize(
    "leftovers",
    [
        pytest.param({TEST_FILE: TEST_TEXT}, id="a-test-file"),
        pytest.param(
            {TEST_FILE: TEST_TEXT, CODE_FILE: CODE_TEXT}, id="a-test-file-and-a-source-file"
        ),
        pytest.param({DOC_FILE: DOC_TEXT}, id="a-document-file"),
    ],
)
def test_a_tests_step_that_keeps_its_own_leftover_test_file_is_not_judged_as_writing_nothing(
    tmp_path: Path, leftovers: dict[str, str]
) -> None:
    recorder, outcome, _ = resumed_over(tmp_path, leftovers, said=CLAIM)

    assert CAUSE not in outcome.detail, outcome.detail
    assert recorder.events.count("claude:tests") == 2, "the killed run and the resumed one: no more"
    assert "stub-checks" in recorder.events


def test_a_leftover_test_file_kept_unchanged_is_committed_as_the_tests_commit(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = resumed_over(tmp_path, {TEST_FILE: TEST_TEXT})

    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == ["test: G1", "feat: G1"]
    assert TEST_FILE in files_in(repo, "HEAD~1")
    assert recorder.events.index("stub-checks") < recorder.events.index("claude:impl")


def test_a_tests_step_over_only_a_leftover_source_file_is_asked_once_more_then_stops(
    tmp_path: Path,
) -> None:
    recorder, outcome, _ = resumed_over(tmp_path, {CODE_FILE: CODE_TEXT}, said=CLAIM)

    assert outcome.status == "failed", outcome.detail
    assert CAUSE in outcome.detail
    assert recorder.events.count("claude:tests") == 3, "the killed run, the resumed one, one retry"
    assert "stub-checks" not in recorder.events
