"""A restack conflict is settled in one session, smallest change first (spec:
restack-conflicts, a conflict is resolved in one session).

The resolver is called once with the order in its prompt, and again, with `follow_up`
naming the failed check, when its result fails one of the pipeline's checks: no marker
left, the unit's own tokens present, none of the unit's own tests missing. A rejected
replayed resolution is such a failed check, not an abort. The resolver stands where the
agent does; git runs for real.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline.restack import (
    ConflictContext,
    Moved,
    RestackConflict,
    conflicted_files,
    move_branch_onto,
)
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRateLimited,
    LoginRejected,
    NetworkUnavailable,
    ServiceUnavailable,
)
from tests.factories import git
from tests.pipeline.test_restack_rerere import landed, sibling, sibling_worktree  # noqa: F401
from tests.prompt_text import flat
from tests.restack_turn_fakes import (
    BRANCH,
    OLD_BASE,
    conflicting_repo,
    keeps_both,
    rebase_in_progress,
)

TEST_FILE = "test_markers.py"
UNIT_TEST = "test_local_stack_is_registered"
TESTS = f"def {UNIT_TEST}():\n    assert True\n"


class Call(NamedTuple):
    prompt: str
    follow_up: str
    cwd: Path
    unmerged: list[str]


class Steps:
    """A resolver that does what its `steps` say, one per call (the last again when
    there are more calls), and keeps what each call was asked."""

    def __init__(self, *steps: Callable[[Path], None]) -> None:
        self.steps = steps
        self.calls: list[Call] = []

    def __call__(self, prompt: str, *, cwd: Path, follow_up: str = "") -> None:
        self.calls.append(Call(prompt, follow_up, cwd, conflicted_files(cwd)))
        self.steps[min(len(self.calls), len(self.steps)) - 1](cwd)


def context() -> ConflictContext:
    return ConflictContext(
        moving_unit="c/2",
        moving_intent="Register the local_stack marker in app",
        onto_unit="c/1",
        onto_intent="Register the integration marker in app",
    )


def move(repo: Path, resolver: Callable[..., None]) -> Moved:
    return move_branch_onto(
        repo, BRANCH, new_base="main", old_base=OLD_BASE, resolve=resolver, context=context()
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`main` and the unit's branch both change markers.py; the branch also adds a test."""
    made = conflicting_repo(tmp_path / "repo")
    git(made, "checkout", "-q", BRANCH)
    (made / TEST_FILE).write_text(TESTS)
    git(made, "add", "-A")
    # In the commit that conflicts, so the paused tree holds the unit's test.
    git(made, "commit", "-q", "--amend", "--no-edit")
    git(made, "checkout", "-q", "main")
    return made


def drops_the_token(cwd: Path) -> None:
    (cwd / "markers.py").write_text('markers = ["integration"]\n')


def leaves_markers(cwd: Path) -> None:
    pass


def drops_the_test(cwd: Path) -> None:
    keeps_both(cwd)
    (cwd / TEST_FILE).unlink()


def keeps_both_and_restores_the_test(cwd: Path) -> None:
    keeps_both(cwd)
    (cwd / TEST_FILE).write_text(TESTS)


def keeps_both_and_edits_a_caller(cwd: Path) -> None:
    keeps_both(cwd)
    (cwd / "notes.md").write_text("notes, for the renamed marker\n")


def test_a_hunk_conflict_is_settled_in_one_call_naming_the_order(repo: Path) -> None:
    resolver = Steps(keeps_both)

    moved = move(repo, resolver)

    assert len(resolver.calls) == 1
    assert moved.resolved == ("markers.py",)
    order = flat(resolver.calls[0].prompt).lower()
    for step in ("conflicting hunks", "depend on the conflict", "port"):
        assert step in order, f"the first prompt does not state the order: {step!r}"
    assert resolver.calls[0].follow_up == ""
    assert not rebase_in_progress(repo)


def test_a_missing_token_gets_a_second_call_naming_it_with_leave_for_dependent_files(
    repo: Path,
) -> None:
    resolver = Steps(drops_the_token, keeps_both_and_edits_a_caller)

    moved = move(repo, resolver)

    first, second = resolver.calls
    assert second.cwd == first.cwd
    assert "local_stack" in second.follow_up
    assert "depend" in flat(second.follow_up).lower()
    assert "local_stack" in second.prompt, "a new session is told what failed too"
    assert "depend on the conflict" in flat(second.prompt).lower(), "and the order"
    assert set(moved.resolved) == {"markers.py", "notes.md"}
    assert git(repo, "show", f"{BRANCH}:notes.md") == "notes, for the renamed marker"
    assert not rebase_in_progress(repo)


def test_a_dropped_test_gets_a_second_call_naming_the_test(repo: Path) -> None:
    resolver = Steps(drops_the_test, keeps_both_and_restores_the_test)

    moved = move(repo, resolver)

    assert len(resolver.calls) == 2
    assert UNIT_TEST in resolver.calls[1].follow_up
    assert "markers.py" in moved.resolved
    assert UNIT_TEST in git(repo, "show", f"{BRANCH}:{TEST_FILE}")


def test_a_call_that_edits_a_file_outside_the_conflict_is_accepted_and_named(
    repo: Path,
) -> None:
    resolver = Steps(keeps_both_and_edits_a_caller)

    moved = move(repo, resolver)

    assert len(resolver.calls) == 1
    assert set(moved.resolved) == {"markers.py", "notes.md"}


def test_a_marker_left_after_the_second_call_ends_the_step_with_the_conflict(
    repo: Path,
) -> None:
    before = git(repo, "rev-parse", BRANCH)
    resolver = Steps(leaves_markers)

    with pytest.raises(RestackConflict, match="left for a human") as caught:
        move(repo, resolver)

    tried = caught.value.tried.splitlines()
    assert len(tried) == 2, "each failed step, for the port that follows"
    assert tried[0].startswith("step 1") and "conflict markers" in tried[0]
    assert tried[1].startswith("step 2") and "conflict markers" in tried[1]
    assert len(resolver.calls) == 2
    assert "conflict markers" in resolver.calls[1].follow_up
    assert "left for a human" not in resolver.calls[1].follow_up, "it is asked to go on"
    assert not rebase_in_progress(repo)
    assert git(repo, "rev-parse", BRANCH) == before
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize(
    "refusal",
    [
        AgentRateLimited("usage limit reached"),
        AgentInterrupted("claude was killed by signal 15"),
        NetworkUnavailable("could not reach the host", strength="strong", host="api.example.test"),
        ServiceUnavailable("overloaded", status=529),
        LoginRejected(Account.default(), "OAuth access token has expired"),
    ],
    ids=["rate-limited", "interrupted", "network", "service", "login"],
)
def test_a_refusal_of_the_second_call_is_raised_as_it_is_with_the_rebase_aborted(
    repo: Path, refusal: Exception
) -> None:
    before = git(repo, "rev-parse", BRANCH)

    def refuses(cwd: Path) -> None:
        raise refusal

    resolver = Steps(drops_the_token, refuses)

    with pytest.raises(type(refusal)):
        move(repo, resolver)

    assert len(resolver.calls) == 2
    assert not rebase_in_progress(repo)
    assert git(repo, "rev-parse", BRANCH) == before


# --- a replayed resolution --------------------------------------------------------------


def test_a_rejected_replay_fails_the_call_and_the_second_call_goes_on(
    landed: tuple[Path, str],  # noqa: F811
    tmp_path: Path,
) -> None:
    repo, pre = landed
    names = ("spec/c/2", "spec/c/3", "spec/c/4")
    for name in names:
        sibling(repo, name, pre)
    trees = {name: sibling_worktree(repo, name, tmp_path) for name in names}

    def run(name: str, resolver: Callable[..., None]) -> Moved:
        return move_branch_onto(
            trees[name],
            name,
            new_base="main",
            old_base=pre,
            resolve=resolver,
            context=context(),
        )

    def derives(cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    def corrects(cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 3  # sibling-fixed\n")

    def rejects(cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("<<<<<<< rejecting the replay\n")

    run("spec/c/2", Steps(derives))
    second = Steps(rejects, corrects)

    moved = run("spec/c/3", second)

    assert moved.resolved == ("conflicted.py",)
    assert len(second.calls) == 2, "the rejection fails the call; it does not abort the move"
    assert second.calls[1].unmerged == ["conflicted.py"], "git staged nothing on its own"
    assert git(trees["spec/c/3"], "show", "spec/c/3:conflicted.py") == "value = 3  # sibling-fixed"
    assert not rebase_in_progress(trees["spec/c/3"])

    arrived: list[str] = []

    def reads_what_arrived(cwd: Path) -> None:
        arrived.append((cwd / "conflicted.py").read_text())
        derives(cwd)

    run("spec/c/4", Steps(reads_what_arrived))

    assert arrived == ["value = 3  # sibling-fixed\n"], (
        "the rejected entry was forgotten, and what the next sibling is offered is the "
        "resolution that replaced it, not the one judged wrong"
    )
