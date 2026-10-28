"""A worktree and a lock per unit.

Units run in parallel, so each gets its own checkout of its repo, and no two
runs may work the same branch at once (docs/architecture.md).

Two rules, both borrowed from sandcastle's worktree handling, decide most of
the behaviour here:

- **Locks fail fast.** E2e-test's lock is a queue, because a second unit's tests
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
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.path_patterns import matches_any
from agent_build_kit.pipeline import host
from agent_build_kit.pipeline.file_lock import file_lock, proc_identity, same_process
from agent_build_kit.pipeline.scratch import ensure_scratch
from agent_build_kit.pipeline.shell import git, git_out, porcelain


class BranchBusy(RuntimeError):
    """Another run holds this branch — a scheduling bug, not a queue."""


class DirtyWorktree(RuntimeError):
    """The worktree has uncommitted changes, which are left for a human."""

    def __init__(self, message: str, paths: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.paths = paths


class WorktreeElsewhere(RuntimeError):
    """The unit's branch is checked out outside the worktree root, which is left alone."""


class WorktreeOccupied(RuntimeError):
    """The path a unit's worktree would take holds something that is not an empty directory."""


class WorktreeEntry(Frozen):
    """One worktree of a repository, as `git worktree list --porcelain` gives it."""

    path: Path
    branch: str | None
    prunable: bool


def _lock_path(branch: str, root: Path) -> Path:
    return root / f"{re.sub(r'[^A-Za-z0-9]', '_', branch)}.lock"


def holder_alive(pid: int, record_host: str | None, started: str | None = None) -> bool:
    """Whether the holder a record names is alive: one of another host always is, this host's
    process table saying nothing of it; a record of this host (or with no host) is judged by
    its pid and, when it recorded one, the process's start time, since a pid alone can be
    reused by an unrelated process."""
    return not host.is_here(record_host) or same_process(pid, started)


def _read_holder(path: Path) -> dict:
    """What the lock file records of its holder: `pid`, `host` and, from a lock written since
    the start time was recorded, `started`. A lock from before that held a pid alone, as a bare
    number or as JSON; one that cannot be read names nobody."""
    try:
        text = path.read_text()
    except OSError:
        return {}
    if text.strip().isdecimal():
        return {"pid": int(text)}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _holder_alive(holder: dict) -> bool:
    """Whether the process a lock names still holds it; a lock naming no pid holds nothing."""
    pid = holder.get("pid")
    return isinstance(pid, int) and holder_alive(pid, holder.get("host"), holder.get("started"))


def lock_holder_gone(branch: str, *, root: Path) -> bool | None:
    """Whether the process named in this branch's lock is gone: `True` only when
    a pid was read and that process is not alive (or the pid now belongs to a
    process with a different start time), `False` for a live one, `None` when there is no
    lock, or one that names no pid. A lock is created before its pid is written,
    so an unreadable one may belong to a holder taking it.
    Unlike `branch_lock`, it leaves the file where it is."""
    holder = _read_holder(_lock_path(branch, root))
    if not isinstance(holder.get("pid"), int):
        return None
    return not _holder_alive(holder)


@contextmanager
def branch_lock(branch: str, *, root: Path):
    """Hold this branch exclusively, or raise `BranchBusy` immediately."""
    root.mkdir(parents=True, exist_ok=True)
    path = _lock_path(branch, root)

    # Judging a stale lock, removing it and creating the new one is a single step: two runs
    # that both found it stale must not each remove the other's fresh lock.
    with file_lock(root / ".claim"):
        if path.exists():
            # A crashed run must not wedge its branch forever, so the pid and its start
            # time are what separate a stale lock from a live one.
            holder = _read_holder(path)
            if _holder_alive(holder):
                raise BranchBusy(
                    f"{branch} is held by pid {holder['pid']} on "
                    f"{holder.get('host') or host.this_host()} "
                    f"since {holder.get('at', 'an unknown time')} ({path})"
                )

            path.unlink(missing_ok=True)

        try:
            # O_EXCL so a run that does not take the claim can't also win.
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise BranchBusy(f"{branch} was claimed by another run") from error

        pid = os.getpid()
        record = {
            "pid": pid,
            "started": proc_identity(pid),
            "host": host.this_host(),
            "branch": branch,
            "at": datetime.now(UTC).isoformat(),
        }
        with os.fdopen(handle, "w") as file:
            json.dump(record, file)

    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def branch_held(branch: str, *, root: Path) -> bool:
    """Whether a live process holds this branch's lock.

    Read, never taken: a probe that claimed the lock would turn away a run starting on the
    branch at the same moment."""
    return lock_holder_gone(branch, root=root) is False


def worktree_key(name: str) -> str:
    """The folder under the worktree root that holds the repo `name`'s worktrees."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def _git_dirs(repo: Path) -> tuple[Path, Path | None] | None:
    """The common git directory of `repo`, and the path of the main working tree when that is
    known, read from the files git keeps. This is the process-free sibling of
    `planning_repo.common_dir`: the sessions page probes a unit's worktree on every listing, and
    listing runs nothing."""
    dot = repo / ".git"
    if dot.is_dir():
        return dot, repo
    if not dot.is_file():
        return None
    text = dot.read_text().strip()
    if not text.startswith("gitdir:"):
        return None
    own = Path(os.path.normpath(repo / text.removeprefix("gitdir:").strip()))
    shared = own / "commondir"
    if not shared.is_file():
        return own, repo  # a separate git directory: `repo` is the main working tree
    common = Path(os.path.normpath(own / shared.read_text().strip()))
    return common, common.parent if common.name == ".git" else None


def _head(admin: Path) -> str | None:
    """The branch the worktree whose git directory is `admin` has checked out, or is rebasing
    when a stopped rebase left its head detached: git treats that branch as checked out."""
    try:
        text = (admin / "HEAD").read_text().strip()
    except OSError:
        return None
    if text.startswith("ref: refs/heads/"):
        return text.removeprefix("ref: refs/heads/")
    return _rebasing_in(admin)


def _rebasing(path: Path) -> str | None:
    """The branch the worktree at `path` is rebasing, if a stopped rebase left it detached."""
    dot = path / ".git"
    try:
        if dot.is_file():
            target = dot.read_text().strip().removeprefix("gitdir:").strip()
            return _rebasing_in(Path(os.path.normpath(path / target)))
    except OSError:
        return None
    return _rebasing_in(dot)


def _rebasing_in(admin: Path) -> str | None:
    for state in ("rebase-merge", "rebase-apply"):
        try:
            rebasing = (admin / state / "head-name").read_text().strip()
        except OSError:
            continue
        if rebasing.startswith("refs/heads/"):
            return rebasing.removeprefix("refs/heads/")
    return None


def _files_untrusted(common: Path, found: Sequence[WorktreeEntry]) -> bool:
    """Whether the heads read from git's files cannot be believed: a repository whose refs live
    in a reftable keeps a fixed stub in every `HEAD` file."""
    if any(entry.branch == ".invalid" for entry in found):
        return True
    try:
        return "refstorage" in (common / "config").read_text().lower()
    except OSError:
        return False


def _porcelain_entries(repo: Path) -> tuple[WorktreeEntry, ...]:
    """The worktrees `git worktree list --porcelain` reports for `repo`."""
    entries = []
    for block in git_out(repo, "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.partition(" ")[::2] for line in block.splitlines() if line.strip())
        if "worktree" not in fields:
            continue
        path = Path(fields["worktree"])
        branch = fields.get("branch", "")
        entries.append(
            WorktreeEntry(
                path=path,
                branch=branch.removeprefix("refs/heads/")
                if branch.startswith("refs/heads/")
                # Git calls a worktree stopped in a rebase detached; it counts as on the branch.
                else _rebasing(path)
                if "detached" in fields
                else None,
                prunable="prunable" in fields,
            )
        )
    return tuple(entries)


def worktree_entries(repo: Path) -> tuple[WorktreeEntry, ...]:
    """Every worktree git lists for `repo`, its own checkout first: what
    `git worktree list --porcelain` says, read from the repository's files so that asking runs
    no process (the sessions page lists on every request). A worktree stopped in a rebase of a
    branch counts as on that branch. Where the files cannot be believed (refs kept in a
    reftable) git is asked."""
    dirs = _git_dirs(repo)
    if dirs is None:
        return ()
    common, main = dirs
    if main is None:
        # The main working tree is not known from the files (a separate git directory, or a
        # bare one), so git is asked rather than leaving it out.
        return _porcelain_entries(repo)
    found = [WorktreeEntry(path=main, branch=_head(common), prunable=False)]
    for admin in sorted((common / "worktrees").glob("*")):
        try:
            recorded = Path((admin / "gitdir").read_text().strip())
        except OSError:
            continue
        # A worktree made with `--relative-paths` records the path relative to `admin`.
        path = Path(os.path.normpath(admin / recorded)).parent
        found.append(WorktreeEntry(path=path, branch=_head(admin), prunable=not path.exists()))
    if _files_untrusted(common, found):
        return _porcelain_entries(repo)
    return tuple(found)


def _under(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _entry_on(repo: Path, branch: str) -> WorktreeEntry | None:
    return next((entry for entry in worktree_entries(repo) if entry.branch == branch), None)


def unit_tree(repo: Path, branch: str, root: Path) -> Path | None:
    """The unit's existing worktree under `root`, or None; never raises."""
    entry = _entry_on(repo, branch)
    if entry is None or entry.prunable or not entry.path.is_dir() or not _under(entry.path, root):
        return None
    return entry.path


def checked_out_elsewhere(repo: Path, branch: str, root: Path) -> Path | None:
    """Where `branch` is checked out when that is not under `root` (the repository's own
    checkout, say), which the pipeline leaves alone; None when it is not, or is under `root`."""
    entry = _entry_on(repo, branch)
    if entry is None or entry.prunable or _under(entry.path, root):
        return None
    return entry.path


def detached_trees(repo: Path, leaf: str, root: Path) -> tuple[Path, ...]:
    """The registered worktrees on no branch whose folder is named `leaf`, two levels under
    `root` whatever the folder between."""
    return tuple(
        entry.path
        for entry in worktree_entries(repo)
        if entry.branch is None
        and not entry.prunable
        and entry.path.name == leaf
        and entry.path.resolve().parent.parent == root.resolve()
    )


def worktree_path(repo: Path, branch: str, root: Path, *, name: str) -> Path:
    """Where a new worktree for `branch` goes: under the folder the repo's `name` in
    `abk.yaml` gives, whatever the checkout's folder is called."""
    return root / worktree_key(name) / re.sub(r"[^A-Za-z0-9]", "_", branch)


def _uncommitted(
    path: Path,
    locks: Sequence[str] = (),
    artifacts: Sequence[str] = (),
    only: Sequence[str] = (),
) -> list[tuple[str, str]]:
    """The worktree's changes without the pipeline's own: a path in `locks`, and an untracked
    path an `artifacts` pattern matches."""
    return [
        (code, name)
        for code, name in porcelain(path, *only)
        if not matches_any(locks, name) and not (code == "??" and matches_any(artifacts, name))
    ]


def changed_paths(
    path: Path, artifacts: Sequence[str] = (), only: Sequence[str] = ()
) -> tuple[str, ...]:
    """The paths a worktree holds uncommitted, every untracked file named; what an
    `artifacts` pattern matches and is untracked is the pipeline's own and left out. With
    `only`, just the paths under those pathspecs."""
    return tuple(name for _, name in _uncommitted(path, artifacts=artifacts, only=only))


def discard_changes(path: Path, artifacts: Sequence[str] = ()) -> None:
    """Restore a worktree to its branch head: tracked files as committed, new files gone.
    Ignored files, such as the scratch folder, stay, and so does an untracked file an
    `artifacts` pattern matches."""
    git_out(path, "reset", "-q", "--hard", "HEAD")
    untracked = git(path, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")
    # A nested repository is listed as one `name/` entry; it stays, as `git clean -fd` left it.
    stray = [
        name
        for name in untracked
        if name and not name.endswith("/") and not matches_any(artifacts, name)
    ]
    for name in stray:
        (path / name).unlink(missing_ok=True)
        for folder in (path / name).parents:  # a folder the removal emptied goes too
            if folder == path:
                break
            try:
                folder.rmdir()
            except OSError:
                break


def commit_changes(path: Path, message: str) -> str:
    """Commit every change in a worktree with `message`, and return the new head."""
    git_out(path, "add", "-A")
    git_out(path, "commit", "-q", "-m", message)
    return git_out(path, "rev-parse", "HEAD")


def prepare_worktree(
    repo: Path,
    branch: str,
    *,
    base: str,
    root: Path,
    name: str,
    allow_dirty: bool = False,
    locks: Sequence[str] = (),
    artifacts: Sequence[str] = (),
) -> Path:
    """The worktree for this unit's branch, created or reused.

    A new branch is created on `base`, which is how a stacked unit starts from
    its parent's work rather than from `main`. An existing worktree is reused
    as it stands, so a re-run continues where the last one stopped — unless it
    is dirty, in which case this raises rather than touching anything, unless
    `allow_dirty` says the caller knows the changes are its own to carry on from.
    A path in `locks` is the pipeline's own, and is never counted, listed or touched; so is
    an untracked path an `artifacts` pattern matches.

    Either way it carries the ignored scratch folder agent runs put long
    command output in (`pipeline/scratch.py`).
    """
    entry = _entry_on(repo, branch)
    if entry is not None and entry.prunable:
        git_out(repo, "worktree", "prune")
        entry = None
    if entry is not None and not _under(entry.path, root):
        raise _elsewhere(branch, entry.path, root)

    if entry is not None:
        path = entry.path
        ensure_scratch(path)
        entries = _uncommitted(path, locks, artifacts)
        if entries and not allow_dirty:
            listing = "\n".join(f"{code} {name}" for code, name in entries)
            raise DirtyWorktree(
                f"{path} has uncommitted changes:\n{listing}\n"
                "Left alone: commit or remove them by hand, since they may be the only copy.",
                paths=tuple(name for _, name in entries),
            )
        return path

    path = worktree_path(repo, branch, root, name=name)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise WorktreeOccupied(f"{path} is where {branch} would go, and it holds something else")
    path.parent.mkdir(parents=True, exist_ok=True)

    branches = git_out(repo, "branch", "--list", branch)
    if branches:
        git_out(repo, "worktree", "add", "-q", str(path), branch)
    else:
        git_out(repo, "worktree", "add", "-q", "-b", branch, str(path), base)

    ensure_scratch(path)
    return path


def _elsewhere(branch: str, path: Path, root: Path) -> WorktreeElsewhere:
    return WorktreeElsewhere(
        f"{branch} is checked out at {path}, which is not under {root}; leave that checkout or "
        "switch it away, the pipeline does not use or remove it"
    )


def prepare_detached(repo: Path, leaf: str, *, ref: str, root: Path, name: str) -> Path:
    """A checkout of `ref` on no branch, created or moved to where `ref` is now.

    For running something *from* main rather than building on it: a
    consumer's dev stack attaches to its platform's, which e2e-test brings up
    from the platform's main, not from the user's own checkout and whatever
    is on it. Nothing is ever committed here, so moving it discards nothing.

    A detached tree named `leaf` under any folder of the root is reused, whatever its key, so
    two repos that share one repository share the tree whichever made it first.
    """
    path = root / worktree_key(name) / leaf
    if not path.exists():
        path = next(iter(detached_trees(repo, leaf, root)), path)
    if path.exists():
        git_out(path, "checkout", "-q", "--detach", ref)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    git_out(repo, "worktree", "add", "-q", "--detach", str(path), ref)
    return path


def superseded_ref(unit_id: str) -> str:
    """The ref a superseded unit's branch tip is kept under."""
    return f"refs/spec-driven/superseded/{unit_id}"


def keep_superseded_tip(repo: Path, branch: str, unit_id: str) -> None:
    """Point `superseded_ref(unit_id)` at the tip of `branch`, for a caller that already holds
    the branch lock. The branch itself and the remote's copy are left as they are."""
    tip = git_out(repo, "rev-parse", "--verify", f"refs/heads/{branch}").strip()
    git(repo, "update-ref", superseded_ref(unit_id), tip)


def keep_superseded_branch(repo: Path, branch: str, unit_id: str, *, lock_root: Path) -> bool:
    """Keep the tip of a superseded unit's branch under `superseded_ref(unit_id)`, with the
    branch lock held. False, with nothing changed, when a live process holds the lock."""
    try:
        with branch_lock(branch, root=lock_root):
            keep_superseded_tip(repo, branch, unit_id)
    except BranchBusy:
        return False
    return True


def remove_worktree(repo: Path, branch: str, *, root: Path) -> None:
    """Drop a finished unit's worktree, keeping its branch and any dirty work.

    `--force` is deliberately not used: if the tree is dirty, git refuses and
    the work stays for a human to look at.
    """
    entry = _entry_on(repo, branch)
    if entry is None:
        return
    if not _under(entry.path, root):
        raise _elsewhere(branch, entry.path, root)
    if not entry.path.exists():
        return

    git(repo, "worktree", "remove", str(entry.path), check=False)
    git_out(repo, "worktree", "prune")
