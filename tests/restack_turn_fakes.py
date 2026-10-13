"""What the restack's turn tests share: a repository with a conflict, a view of
which git commands ran while the repository's turn was held, and the stack
move handler wired as `abk` wires it.

The turn is the real lock file, taken through `file_lock`. Whether it is held
is read with `try_file_lock` from a thread of its own, so the answer is the one
another unit's thread would get. Git runs for real; the spy only notes, before
each command, whether the turn is held, then runs it.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import restack, shell, workspaces
from agent_build_kit.pipeline.file_lock import try_file_lock
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.runtimes import AgentRequest
from tests.conftest import make_installation
from tests.factories import git, init_repo, stored_unit
from tests.runtimes.stand_in import StandInRuntime

BRANCH = "spec/c/2"
OLD_BASE = "spec/c/1"
RESOLVER = ("<resolver>",)


def sh(repo: Path, *args: str) -> str:
    """git, without the spy: what a test or another writer does on its own."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def commit_file(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"write {name}")


def conflicting_repo(path: Path) -> Path:
    """`main` and `spec/c/2` both change markers.py in different ways."""
    repo = init_repo(path)
    commit_file(repo, "markers.py", "markers = []\n")
    commit_file(repo, "notes.md", "notes\n")
    git(repo, "checkout", "-q", "-b", OLD_BASE)
    git(repo, "checkout", "-q", "-b", BRANCH)
    commit_file(repo, "markers.py", 'markers = ["local_stack"]\n')
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "markers.py", 'markers = ["integration"]\n')
    return repo


def keeps_both(cwd: Path) -> None:
    (cwd / "markers.py").write_text('markers = ["integration", "local_stack"]\n')


def extra_commit(repo: Path, branch: str, name: str, scratch: Path) -> str:
    """A commit on top of `branch` that adds `name`, made in a worktree of its own
    and left on no branch: where another writer would have moved `branch` to."""
    git(repo, "worktree", "add", "-q", "--detach", str(scratch), branch)
    commit_file(scratch, name, f"{name}\n")
    sha = git(scratch, "rev-parse", "HEAD")
    git(repo, "worktree", "remove", "--force", str(scratch))
    return sha


def rebase_in_progress(tree: Path) -> bool:
    return any(
        (tree / sh(tree, "rev-parse", "--git-path", name)).exists()
        for name in ("rebase-merge", "rebase-apply")
    )


def lock_is_held(lock: Path) -> bool:
    """Whether the turn is held, asked from a thread that is not the holder's."""
    answer: list[bool] = []

    def probe() -> None:
        with try_file_lock(lock) as taken:
            answer.append(not taken)

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    return answer[0]


def run_bounded[T](step: Callable[[], T], *, seconds: float = 60) -> T:
    """`step` in a thread, failing the test when it does not end: a turn taken
    while it is held waits for itself for ever."""
    outcome: list[T] = []
    raised: list[BaseException] = []

    def target() -> None:
        try:
            outcome.append(step())
        except BaseException as error:
            raised.append(error)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=seconds)
    if thread.is_alive():
        pytest.fail("the step did not end: the turn was taken while it was held")
    if raised:
        raise raised[0]
    return outcome[0]


class GitCall(NamedTuple):
    verb: tuple[str, ...]
    held: bool
    cwd: Path


def verb_of(args: tuple[str, ...]) -> tuple[str, ...]:
    """The git command without the `-c key=value` pairs that ride in front of it."""
    start = 0
    while start < len(args) and args[start] == "-c":
        start += 2
    return args[start:]


def writes_shared_state(call: GitCall) -> bool:
    verb = call.verb
    return verb[0] in {"rebase", "rerere", "add", "update-ref"} or verb[:2] in {
        ("worktree", "add"),
        ("worktree", "remove"),
        ("worktree", "prune"),
    }


def spy_git(monkeypatch: pytest.MonkeyPatch, lock: Path) -> list[GitCall]:
    """Every git command the pipeline makes from now on, in order, with whether
    `lock` was held when it started. `mark_resolver` adds the agent's own moment."""
    calls: list[GitCall] = []
    real = shell.git

    def spy(repo: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(GitCall(verb_of(args), lock_is_held(lock), Path(repo)))
        return real(repo, *args, **kwargs)

    monkeypatch.setattr(shell, "git", spy)
    monkeypatch.setattr(workspaces, "git", spy)
    return calls


def around_the_resolver(calls: list[GitCall]) -> tuple[list[GitCall], GitCall, list[GitCall]]:
    """The commands before the agent's moment, that moment, and the commands after it."""
    at = next(i for i, call in enumerate(calls) if call.verb == RESOLVER)
    return calls[:at], calls[at], calls[at + 1 :]


def mark_resolver(calls: list[GitCall], lock: Path, cwd: Path) -> None:
    calls.append(GitCall(RESOLVER, lock_is_held(lock), cwd))


class Counting:
    """A turn factory that counts how often the turn was taken."""

    def __init__(self, turn: Callable[[], Any]) -> None:
        self.turn = turn
        self.taken = 0

    def __call__(self):
        self.taken += 1
        return self.turn()


class Rig:
    """The stack move handler as `build_stack_moves` wires it, over a repository with
    a conflicting branch that has no worktree of its own, and an agent that is
    whatever `act` says."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.installation: Installation = make_installation(
            tmp_path / "planning", planning=dict(worktree_root=str(tmp_path / "trees"))
        )
        self.repo = conflicting_repo(self.installation.checkouts["app"])
        self.lock = self.installation.state_dir / "locks" / "repo-app.lock"
        self.store = UnitStore(tmp_path / "units.json")
        self.child: StoredUnit = stored_unit(
            "c/2", change="c", title="Register the local_stack marker", branch=BRANCH
        )
        self.parent: StoredUnit = stored_unit(
            "c/1", change="c", title="Register the integration marker", branch=OLD_BASE
        )
        self.store.upsert([self.child, self.parent])
        self.branch = BRANCH
        self.requests: list[AgentRequest] = []
        self.act: Callable[[AgentRequest], None] = lambda request: keeps_both(
            request.cwd or self.repo
        )
        # The agent's runtime, made over `act`: a test that needs more of a runtime gives its own.
        self.runtime: Callable[..., StandInRuntime] = StandInRuntime

    def restack(self) -> None:
        self.prepared()()

    def prepared(self) -> Callable[[], None]:
        """The restack as a piece of work to run later, over the handler wired as `abk` wires it."""

        def act(request: AgentRequest) -> None:
            self.requests.append(request)
            self.act(request)

        runtime = self.runtime(act=act)
        self.monkeypatch.setattr(runtimes, "active", lambda: runtime)
        self.moves = cli.build_stack_moves(self.store, self.installation)
        return partial(
            self.moves["restack"],
            branch=self.branch,
            old_base=OLD_BASE,
            new_base="main",
            child=self.child,
            parent=self.parent,
        )

    def use_clean_approved_branch(self) -> str:
        """Moves `spec/c/3` instead: it applies cleanly onto `main`, and its head is approved."""
        git(self.repo, "checkout", "-q", "-b", "spec/c/3", OLD_BASE)
        commit_file(self.repo, "extra.py", "EXTRA = 1\n")
        head = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        self.branch = "spec/c/3"
        self.child = self.child.model_copy(update={"branch": self.branch, "approved": head})
        return head

    def temporary_tree(self) -> Path:
        return restack.temporary_tree(self.repo, self.branch, root=self.installation.worktree_root)
