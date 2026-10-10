"""Keeping the pipeline's own environment current, and telling it healthy.

The `environment` section holds argv lists and path lists; nothing here knows a
package manager. The tick hashes the inputs, runs `sync` when they changed, runs
`check`, and heals once when `check` fails. The result is recorded in the state
directory for `abk status`, and units use `problem` to tell a broken environment
from their own failure.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.config import EnvironmentConfig, RepoConfig, active
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.path_patterns import inside, matches_any, matching_files, normalize
from agent_build_kit.pipeline.command_limit import run_limited
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.shell import git, git_out

RECORD = "environment.json"


class EnvironmentState(Frozen):
    """What the last tick found: the inputs' hash at the last sync, and the health."""

    hash: str = ""
    healthy: bool = True
    output: str = ""
    since: str = ""


def matched_inputs(environment: EnvironmentConfig, root: Path) -> dict[str, list[str]]:
    """Per input pattern, the files under `root` it matches; the artifacts are left out."""
    inputs = environment.inputs
    return matching_files(
        root, (*inputs.dependencies, *inputs.lock, *inputs.other), excluding=environment.artifacts
    )


def _literal_name(pattern: str) -> str | None:
    """The name a literal pattern matches as, so a file it names alone is not hashed twice."""
    try:
        return normalize(pattern)
    except ValueError:
        return os.path.normpath(pattern)  # an input leaving the repository, still allowed


def inputs_hash(environment: EnvironmentConfig, root: Path) -> str:
    """A hash of every input pattern as written, the sorted files it matches and their
    contents; a pattern matching nothing counts as missing. A literal path hashes as the
    one-file pattern it is."""
    digest = hashlib.sha256()
    for pattern, names in matched_inputs(environment, root).items():
        digest.update(pattern.encode() + b"\0")
        if not names:
            digest.update(b"<missing>\0")
        for name in names:
            if name != _literal_name(pattern):
                digest.update(name.encode() + b"\0")
            digest.update((root / name).read_bytes() + b"\0")
    return digest.hexdigest()


def read_state(state_dir: Path) -> EnvironmentState | None:
    try:
        return EnvironmentState.model_validate(json.loads((state_dir / RECORD).read_text()))
    except (OSError, ValueError):
        return None


def _write_state(state_dir: Path, state: EnvironmentState) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    temporary = state_dir / f"{RECORD}.tmp"
    temporary.write_text(state.model_dump_json())
    temporary.replace(state_dir / RECORD)


def _run(command: list[str], root: Path) -> tuple[bool, str]:
    """Whether `command` exits 0 in `root`, and what it printed."""
    limits = active().limits
    try:
        result = run_limited(
            command,
            limit=limits.tier1_command_seconds,
            grace=limits.tier1_abort_grace_seconds,
            cwd=root,
        )
    except OSError as error:
        return False, f"{' '.join(command)} could not run: {error}"
    output = f"{result.stdout or ''}{result.stderr or ''}".strip()
    return result.returncode == 0, output


def problem(root: Path) -> str | None:
    """Why the pipeline's environment is unhealthy now: the output of a failing
    `check`. None when it is healthy, and when no environment is managed."""
    environment = active().environment
    if environment is None:
        return None
    ok, output = _run(environment.check, root)
    return None if ok else output or f"{' '.join(environment.check)} failed"


class WorktreeFault(Frozen):
    """A repository's environment failing in a unit's worktree: what it printed, and
    whether it is the environment's (the unit left the inputs as the base has them) or
    the unit's own (its branch changed them, so a failing `sync` or `check` is its to fix)."""

    output: str
    environment: bool


WORKTREE_RECORD = "abk-environment-hash"


def lock_paths(repo: RepoConfig | None) -> tuple[str, ...]:
    """The lock files a repository's environment names, relative to the worktree root.
    They are the pipeline's own in its worktrees; empty when it declares no environment."""
    environment = repo.environment if repo else None
    if environment is None:
        return ()
    return tuple(normalize(name) for name in inside(environment.inputs.lock))


def _base_inputs(
    tree: Path, point: str, patterns: list[str], excluding: list[str]
) -> dict[str, str]:
    """The files `patterns` match at `point`, with git's object id of each."""
    listing = git(tree, "ls-tree", "-r", "-z", point).stdout.split("\0")
    found: dict[str, str] = {}
    for entry in filter(None, listing):
        meta, name = entry.split("\t", 1)
        if matches_any(patterns, name) and not matches_any(excluding, name):
            found[name] = meta.split()[2]
    return found


def _changed_from_base(
    environment: EnvironmentConfig, tree: Path, base: str, patterns: list[str] | None = None
) -> bool:
    """Whether the unit changed the inputs (or just those `patterns` match): the files the
    worktree has against those the base had at the point the branch left it. Compared as
    git's own object ids, so line endings and encodings are never decoded."""
    inputs = environment.inputs
    if patterns is None:
        patterns = [*inputs.dependencies, *inputs.lock, *inputs.other]
    patterns = inside(patterns)  # a path outside the repository is not the unit's to change
    fork = git(tree, "merge-base", base, "HEAD", check=False)
    point = fork.stdout.strip() if fork.returncode == 0 and fork.stdout.strip() else base
    there = _base_inputs(tree, point, patterns, environment.artifacts)
    here = {
        name
        for names in matching_files(tree, patterns, excluding=environment.artifacts).values()
        for name in names
    }
    if here != there.keys():
        return True
    return any(git_out(tree, "hash-object", "--", name) != there[name] for name in here)


def _tracked_locks(tree: Path, patterns: tuple[str, ...]) -> list[str]:
    """The lock files, matched by `patterns`, the branch's head holds."""
    held = git(tree, "ls-tree", "-r", "--name-only", "-z", "HEAD", check=False).stdout.split("\0")
    return [name for name in held if name and matches_any(patterns, name)]


def restore_unchanged_locks(repo: RepoConfig | None, tree: Path, base: str) -> None:
    """Put each tracked lock file back as the branch has it, unless the unit changed a
    dependency input: a rewrite made without one is noise, and would be swept into an
    unrelated commit or stop a move of the branch."""
    environment = repo.environment if repo else None
    if environment is None:
        return
    if _changed_from_base(environment, tree, base, environment.inputs.dependencies):
        return
    for name in _tracked_locks(tree, lock_paths(repo)):
        git_out(tree, "checkout", "-q", "--", name)


def artifact_patterns(repo: RepoConfig | None) -> tuple[str, ...]:
    """The path patterns of what a repository's environment produces; empty when it
    declares none. They are the pipeline's own in its worktrees."""
    environment = repo.environment if repo else None
    return tuple(environment.artifacts) if environment else ()


def repo_artifacts(inst: Installation, name: str) -> tuple[str, ...]:
    """The artifact patterns of the repository `name` in the installation; empty for a name
    that is not one, such as the planning repository."""
    return artifact_patterns(inst.config.repos.get(name))


def _unstage(tree: Path, names: list[str]) -> None:
    """Take `names` out of the index in one git call; the files stay in the worktree."""
    if names:
        git(
            tree,
            "rm",
            "-q",
            "--cached",
            "--ignore-unmatch",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
            input="\0".join(names),
        )


def unstage_artifacts(repo: RepoConfig | None, tree: Path) -> None:
    """Take out of the index each new file an artifact pattern matches, so that a commit
    never holds what a sync built; the files stay in the worktree. A file the branch
    already tracks is ordinary work and stays staged."""
    patterns = artifact_patterns(repo)
    if not patterns:
        return
    added = git_out(
        tree, "diff", "--cached", "--no-renames", "--name-only", "-z", "--diff-filter=A"
    ).split("\0")
    _unstage(tree, [name for name in added if name and matches_any(patterns, name)])


def unstage_untracked_locks(repo: RepoConfig | None, tree: Path) -> None:
    """Take out of the index a lock file the branch does not track: the repository
    chose not to commit it, and it stays in the worktree."""
    patterns = lock_paths(repo)
    tracked = _tracked_locks(tree, patterns)
    present = matching_files(tree, patterns, excluding=artifact_patterns(repo))
    _unstage(tree, [name for names in present.values() for name in names if name not in tracked])


def prepare_worktree(repo: RepoConfig | None, tree: Path, base: str) -> WorktreeFault | None:
    """Bring a repository's environment up to date in a unit's worktree: `sync` when the
    inputs' hash differs from the one recorded for this worktree, then `check`. None when
    healthy, or when the repository declares no environment."""
    environment = repo.environment if repo else None
    if environment is None:
        return None
    record = Path(git_out(tree, "rev-parse", "--absolute-git-dir")) / WORKTREE_RECORD
    digest = inputs_hash(environment, tree)
    failure = ""
    if not record.is_file() or record.read_text() != digest:
        ok, output = _run(environment.sync, tree)
        if ok:
            record.write_text(digest)
        else:
            failure = output or f"{' '.join(environment.sync)} failed"
    if not failure:
        ok, output = _run(environment.check, tree)
        if not ok:
            failure = output or f"{' '.join(environment.check)} failed"
    if not failure:
        return None
    return WorktreeFault(
        output=failure, environment=not _changed_from_base(environment, tree, base)
    )


def ensure(inst: Installation, *, say: Callable[[str], None]) -> bool:
    """Bring the environment up to date before a pass starts work. True when the
    pass may go on: healthy, or none managed. A failure is recorded and printed.
    The new inputs hash is kept only by a sync that exited 0, so a failed sync is
    tried again on the next tick."""
    environment = inst.config.environment
    if environment is None:
        return True
    with file_lock(inst.state_dir / "environment.lock"):
        previous = read_state(inst.state_dir) or EnvironmentState()
        digest = inputs_hash(environment, inst.root)
        hash_ = previous.hash
        synced = ""

        def sync() -> None:
            nonlocal hash_, synced
            ok, synced = _run(environment.sync, inst.root)
            if ok:
                hash_ = digest
            else:
                say(f"environment sync failed: {synced}")

        if digest != previous.hash:
            say("environment inputs changed: syncing")
            sync()
        ok, output = _run(environment.check, inst.root)
        if not ok:
            say("environment check failed: syncing and checking again")
            sync()
            ok, output = _run(environment.check, inst.root)
        now = datetime.now(UTC).isoformat()
        if ok:
            _write_state(inst.state_dir, EnvironmentState(hash=hash_, healthy=True, since=now))
            return True
        shown = output or synced or "the check failed with no output"
        since = previous.since if not previous.healthy else now
        _write_state(
            inst.state_dir, EnvironmentState(hash=hash_, healthy=False, output=shown, since=since)
        )
        say(f"environment unhealthy, starting nothing: {shown}")
        return False


__all__ = [
    "EnvironmentState",
    "WorktreeFault",
    "ensure",
    "artifact_patterns",
    "inputs_hash",
    "lock_paths",
    "matched_inputs",
    "prepare_worktree",
    "repo_artifacts",
    "problem",
    "read_state",
    "restore_unchanged_locks",
    "unstage_artifacts",
    "unstage_untracked_locks",
]
