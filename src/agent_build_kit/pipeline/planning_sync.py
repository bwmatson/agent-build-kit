"""The role of a planning root, the pipeline marker, and the one sync of the pipeline worktree."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.planning_repo import (
    common_dir,
    current_branch,
    default_branch_of,
    git_dir,
    is_repo,
    repo_sharing,
    restore_default_branch,
)
from agent_build_kit.pipeline.shell import git, has_origin

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation


class PlanningMode(StrEnum):
    SEPARATE = "separate"
    WORKING_COPY = "working copy"
    PIPELINE_WORKTREE = "pipeline worktree"


class SyncOutcome(StrEnum):
    SYNCED = "synced"
    CURRENT = "current"
    AHEAD = "ahead"
    STOPPED = "stopped"
    SKIPPED = "skipped"


class SyncResult(Frozen):
    outcome: SyncOutcome
    reason: str = ""


MARKER_NAME = "abk-pipeline-worktree"

# Files a git directory holds while an operation is unfinished, and what to call it.
UNFINISHED = {
    "MERGE_HEAD": "merge",
    "rebase-merge": "rebase",
    "rebase-apply": "rebase",
    "CHERRY_PICK_HEAD": "cherry-pick",
    "REVERT_HEAD": "revert",
}


def _one_line(text: str) -> str:
    return " ".join(text.split())


def marker_path(root: Path) -> Path:
    """The pipeline marker of the repository `root` is in: one file in the common git directory."""
    common = common_dir(root)
    if common is None:
        raise ValueError(f"{root} is not in a git repository")
    return common / MARKER_NAME


def write_pipeline_marker(root: Path, worktree: Path) -> Path:
    path = marker_path(root)
    path.write_text(f"{worktree.resolve()}\n")
    return path


def read_pipeline_marker(root: Path) -> Path | None:
    """The path the marker names, whether or not it still exists; None with no marker."""
    path = marker_path(root)
    if not path.is_file():
        return None
    return Path(path.read_text().strip())


def remove_pipeline_marker(root: Path) -> None:
    marker_path(root).unlink(missing_ok=True)


def is_pipeline_worktree(root: Path) -> bool:
    """Whether `root` is the path its repository's marker names. A pipeline worktree is always a
    linked one, whose `.git` is a file, so no other root asks git."""
    if not (root / ".git").is_file() or common_dir(root) is None:
        return False
    named = read_pipeline_marker(root)
    return named is not None and named.resolve() == root.resolve()


def live_pipeline_worktree(inst: Installation) -> Path | None:
    """The pipeline worktree the marker names, when it exists."""
    if not is_repo(inst.root):
        return None
    named = read_pipeline_marker(inst.root)
    return named if named is not None and named.is_dir() else None


def in_repo_name(inst: Installation) -> str | None:
    """The listed repo whose checkout is in the planning root's own repository."""
    return repo_sharing(inst.checkouts, inst.root)


def planning_mode(inst: Installation) -> PlanningMode:
    if in_repo_name(inst) is None:
        return PlanningMode.SEPARATE
    live = live_pipeline_worktree(inst)
    if live is not None and live.resolve() == inst.root.resolve():
        return PlanningMode.PIPELINE_WORKTREE
    return PlanningMode.WORKING_COPY


def in_repo_default_branch(inst: Installation) -> str:
    """The in-repo repo's `default_branch`, as verify reads it."""
    name = in_repo_name(inst)
    return inst.repo(name).default_branch if name else default_branch_of(inst.root)


def default_tip_ref(root: Path, default: str) -> str:
    """The ref holding the default branch's tip: origin's when the repository has an origin,
    else the local branch."""
    return f"refs/remotes/origin/{default}" if has_origin(root) else f"refs/heads/{default}"


def _stopped(reason: str) -> SyncResult:
    return SyncResult(outcome=SyncOutcome.STOPPED, reason=_one_line(reason))


def _sync_separate(inst: Installation, say: Callable[[str], None]) -> SyncResult:
    if not is_repo(inst.root):
        return SyncResult(outcome=SyncOutcome.SKIPPED)
    branch = default_branch_of(inst.root)
    if not restore_default_branch(inst.root, branch, say):
        return _stopped(f"cannot check out {branch}")
    if not has_origin(inst.root):
        return SyncResult(outcome=SyncOutcome.CURRENT)
    pulled = git(inst.root, "pull", "--ff-only", "origin", branch, check=False)
    if pulled.returncode != 0:
        return _stopped(pulled.stderr)
    return SyncResult(outcome=SyncOutcome.SYNCED)


def _sync_worktree(inst: Installation, say: Callable[[str], None]) -> SyncResult:
    root = inst.root
    own_dir = git_dir(root)
    if own_dir is not None:
        for name, what in UNFINISHED.items():
            if (own_dir / name).exists():
                return _stopped(f"a {what} is unfinished in {root}")
    branch = current_branch(root)
    if branch:
        return _stopped(f"HEAD is on the branch {branch}, which is kept")
    default = in_repo_default_branch(inst)
    if has_origin(root):
        fetched = git(root, "fetch", "origin", default, check=False)
        if fetched.returncode != 0:
            return _stopped(fetched.stderr)
    tip_ref = default_tip_ref(root, default)
    tip = git(root, "rev-parse", "--verify", tip_ref, check=False)
    if tip.returncode != 0:
        return _stopped(f"{tip_ref} does not exist")
    tip_sha = tip.stdout.strip()
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    if head == tip_sha:
        return SyncResult(outcome=SyncOutcome.CURRENT)
    if git(root, "merge-base", "--is-ancestor", head, tip_sha, check=False).returncode == 0:
        merged = git(root, "merge", "--ff-only", tip_sha, check=False)
        if merged.returncode != 0:
            return _stopped(merged.stderr or merged.stdout)
        say(f"planning worktree moved to {tip_ref} ({tip_sha[:10]})")
        return SyncResult(outcome=SyncOutcome.SYNCED)
    if git(root, "merge-base", "--is-ancestor", tip_sha, head, check=False).returncode == 0:
        say(f"planning worktree is ahead of {tip_ref} — leaving it")
        return SyncResult(outcome=SyncOutcome.AHEAD)
    own = git(root, "rev-list", "--count", f"{tip_sha}..{head}").stdout.strip()
    new = git(root, "rev-list", "--count", f"{head}..{tip_sha}").stdout.strip()
    return _stopped(f"diverged: {own} commits of its own, {new} new")


def sync_planning(inst: Installation, say: Callable[[str], None]) -> SyncResult:
    """Brings the planning root to the default branch's tip before a run. Nothing is stashed,
    reset or deleted; a `SyncOutcome.STOPPED` carries the one reason."""
    mode = planning_mode(inst)
    if mode == PlanningMode.WORKING_COPY:
        return SyncResult(outcome=SyncOutcome.SKIPPED)
    if not inst.config.planning.self_pull:
        say(f"planning.self_pull is off — not syncing {inst.root}")
        return SyncResult(outcome=SyncOutcome.SKIPPED)
    if mode == PlanningMode.SEPARATE:
        return _sync_separate(inst, say)
    return _sync_worktree(inst, say)


def sync_or_stop(inst: Installation, say: Callable[[str], None]) -> bool:
    """Syncs the planning root; on a stop says the one `planning sync stopped: <reason>` line and
    returns False, so the caller ends its run."""
    result = sync_planning(inst, say)
    if result.outcome == SyncOutcome.STOPPED:
        say(f"planning sync stopped: {result.reason}")
        return False
    return True
