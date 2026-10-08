"""A worktree and a lock per unit.

Units run in parallel, so each gets its own checkout of its repo, and no two
runs may work the same branch at once (docs/architecture.md).

Two rules, both borrowed from sandcastle's worktree handling, decide most of
the behaviour here:

- **Locks fail fast.** Tier 2's lock is a queue, because a second unit's tests
  are valid and simply can't run yet. This one isn't: two runs on one branch
  means the scheduler handed the same unit out twice. Waiting would hide that
  bug; failing surfaces it.
- **Agent work is never discarded.** An existing worktree is reused, with
  whatever commits are already on its branch — that is the point of
  deterministic branch names. A *dirty* worktree is reported rather than
  cleaned or reused: uncommitted changes may be the only copy of something,
  and committing them into the wrong unit is as bad as deleting them.

Locks live outside the worktrees, because anything inside one is visible to
the agent working there, which could delete it or commit it by accident.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.pipeline.scratch import ensure_scratch
from agent_build_kit.pipeline.shell import git, git_out


class BranchBusy(RuntimeError):
    """Another run holds this branch — a scheduling bug, not a queue."""


class DirtyWorktree(RuntimeError):
    """The worktree has uncommitted changes, which are left for a human."""

    def __init__(self, message: str, paths: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.paths = paths


def _lock_path(branch: str, root: Path) -> Path:
    return root / f"{re.sub(r'[^A-Za-z0-9]', '_', branch)}.lock"


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Someone else's process, but alive.
    return True


def lock_holder_gone(branch: str, *, root: Path) -> bool | None:
    """Whether the process named in this branch's lock is gone: `True` for a
    dead holder, `False` for a live one, `None` when there is no lock to read.
    Unlike `branch_lock`, it leaves the file where it is."""
    path = _lock_path(branch, root)
    try:
        parsed = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return True
    pid = parsed.get("pid") if isinstance(parsed, dict) else None
    return not (isinstance(pid, int) and _process_alive(pid))


@contextmanager
def branch_lock(branch: str, *, root: Path):
    """Hold this branch exclusively, or raise `BranchBusy` immediately."""
    root.mkdir(parents=True, exist_ok=True)
    path = _lock_path(branch, root)

    if path.exists():
        # A crashed run must not wedge its branch forever, so the pid is what
        # separates a stale lock from a live one. Parsing is kept apart from
        # reporting on purpose: a missing field while building the message
        # must not be mistaken for an unreadable lock.
        holder: dict = {}
        try:
            parsed = json.loads(path.read_text())
            holder = parsed if isinstance(parsed, dict) else {}
        except (OSError, ValueError):
            holder = {}

        pid = holder.get("pid")
        if isinstance(pid, int) and _process_alive(pid):
            raise BranchBusy(
                f"{branch} is held by pid {pid} since {holder.get('at', 'an unknown time')}"
            )

        path.unlink(missing_ok=True)

    try:
        # O_EXCL so two processes racing here can't both win.
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise BranchBusy(f"{branch} was claimed by another run") from error

    with os.fdopen(handle, "w") as file:
        json.dump({"pid": os.getpid(), "branch": branch, "at": datetime.now(UTC).isoformat()}, file)

    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def worktree_path(repo: Path, branch: str, root: Path) -> Path:
    return root / repo.name / re.sub(r"[^A-Za-z0-9]", "_", branch)


def _porcelain(path: Path) -> list[tuple[str, str]]:
    """The worktree's changes as (status code, exact path), every untracked file named."""
    fields = git(path, "status", "--porcelain", "-z", "--untracked-files=all").stdout.split("\0")
    entries: list[tuple[str, str]] = []
    pending = iter(fields)
    for field in pending:
        if not field:
            continue
        code, name = field[:2], field[3:]
        if "R" in code or "C" in code:
            next(pending, None)  # the source of a rename or copy follows as its own field
        entries.append((code, name))
    return entries


def prepare_worktree(
    repo: Path, branch: str, *, base: str, root: Path, allow_dirty: bool = False
) -> Path:
    """The worktree for this unit's branch, created or reused.

    A new branch is created on `base`, which is how a stacked unit starts from
    its parent's work rather than from `main`. An existing worktree is reused
    as it stands, so a re-run continues where the last one stopped — unless it
    is dirty, in which case this raises rather than touching anything, unless
    `allow_dirty` says the caller knows the changes are its own to carry on from.

    Either way it carries the ignored scratch folder agent runs put long
    command output in (`pipeline/scratch.py`).
    """
    path = worktree_path(repo, branch, root)

    if path.exists():
        ensure_scratch(path)
        entries = _porcelain(path)
        if entries and not allow_dirty:
            listing = "\n".join(f"{code} {name}" for code, name in entries)
            raise DirtyWorktree(
                f"{path} has uncommitted changes:\n{listing}\n"
                "Left alone: commit or remove them by hand, since they may be the only copy.",
                paths=tuple(name for _, name in entries),
            )
        return path

    path.parent.mkdir(parents=True, exist_ok=True)

    branches = git_out(repo, "branch", "--list", branch)
    if branches:
        git_out(repo, "worktree", "add", "-q", str(path), branch)
    else:
        git_out(repo, "worktree", "add", "-q", "-b", branch, str(path), base)

    ensure_scratch(path)
    return path


def prepare_detached(repo: Path, name: str, *, ref: str, root: Path) -> Path:
    """A checkout of `ref` on no branch, created or moved to where `ref` is now.

    For running something *from* main rather than building on it: a
    consumer's dev stack attaches to its platform's, which tier 2 brings up
    from the platform's main, not from the user's own checkout and whatever
    is on it. Nothing is ever committed here, so moving it discards nothing.
    """
    path = root / repo.name / name
    if path.exists():
        git_out(path, "checkout", "-q", "--detach", ref)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    git_out(repo, "worktree", "add", "-q", "--detach", str(path), ref)
    return path


def remove_worktree(repo: Path, branch: str, *, root: Path) -> None:
    """Drop a finished unit's worktree, keeping its branch and any dirty work.

    `--force` is deliberately not used: if the tree is dirty, git refuses and
    the work stays for a human to look at.
    """
    path = worktree_path(repo, branch, root)
    if not path.exists():
        return

    git(repo, "worktree", "remove", str(path), check=False)
    git_out(repo, "worktree", "prune")
