"""Carry a unit that landed off the default branch onto it."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

from agent_build_kit.config import RepoConfig
from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline import events, shell
from agent_build_kit.pipeline.restack import (
    ConflictContext,
    Resolver,
    RestackConflict,
    Turn,
    ask_resolver,
    conflict_prompt,
    git,
    push_with_lease,
    read_conflict,
    take_generated_from_base,
)
from agent_build_kit.pipeline.unit_store import Cause, Pull, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED
from agent_build_kit.pipeline.workspaces import BranchBusy, worktree_key

CARRY_ROLE = "carry"
CARRY_REFUSED = "carry_refused"

CARRY_NOTE = """
This is a cherry-pick onto the default branch, not a rebase. If it cannot be resolved the carry
is abandoned and the unit stays held for a person.
"""


def carry_branch(unit_id: str) -> str:
    """The branch a unit's carry is made on."""
    return f"spec/{unit_id}/carry"


def is_carrying(unit: StoredUnit) -> bool:
    """Whether the unit has a pull request that carries it already."""
    return any(pull.role == CARRY_ROLE for pull in unit.pulls)


def carry(
    store: UnitStore,
    unit_id: str,
    *,
    forge: Forge,
    repo_id: RepoId,
    repo: Path,
    default_branch: str,
    worktrees: Path,
    resolve: Resolver | None = None,
    repo_config: RepoConfig | None = None,
    turn: Turn = nullcontext,
) -> None:
    """Cherry-pick the unit's merge commit onto `spec/<unit>/carry`, a branch off the default
    branch (as the remote has it, after a fetch) made in a worktree under `worktrees`, and open
    a pull request against the default branch, recorded as role `carry`. The unit is `in_review`
    with cause `carried`; one that already carries is left alone, and a cherry-pick that leaves
    nothing to commit opens no pull request and records the unit `merged`.

    A conflict is resolved as a restack's is (`ask_resolver`: both sides' intent, generated
    files from the base, the answer checked). One that cannot be resolved aborts the cherry-pick
    and raises `RestackConflict`, with no pull request opened and the unit as it was."""
    unit = store.get(unit_id)
    if is_carrying(unit):
        return
    sha = unit.merge_sha or next(
        (pull.merge_sha for pull in reversed(unit.pulls) if pull.merge_sha), None
    )
    if sha is None:
        raise ValueError(f"{unit_id}: no commit recorded to carry")
    branch = carry_branch(unit_id)
    path = worktrees / worktree_key(unit_id) / "carry"
    path.parent.mkdir(parents=True, exist_ok=True)
    start = default_branch
    with turn():
        if shell.has_origin(repo):
            git(repo, "fetch", "-q", "origin", default_branch, check=False)
            start = f"refs/remotes/origin/{default_branch}"
        git(repo, "worktree", "prune", check=False)
        git(repo, "worktree", "add", "-q", "-B", branch, str(path), start)
    try:
        context = ConflictContext(
            moving_unit=unit_id,
            moving_intent=f"{unit.title} (already merged into another branch, carried here)",
            onto_unit=default_branch,
            onto_intent="the default branch as it stands",
            moving_change=unit.change,
            moving_repo=unit.repo,
            repo=repo_config,
        )
        if not _pick(path, sha, resolve, context, repo_config, turn):
            store.set_state(unit_id, MERGED, note=f"its changes are already on {default_branch}")
            return
        with turn():
            push_with_lease(path, branch, last_pushed=None)
    finally:
        with turn():
            git(repo, "worktree", "remove", "--force", str(path), check=False)
    first = next((pull.number for pull in unit.pulls if pull.role != CARRY_ROLE), unit.pr)
    number = forge.create_pr(
        repo_id,
        head=branch,
        base=default_branch,
        title=f"Carry {unit_id} onto {default_branch}",
        body=(
            f"{unit_id} was merged into a branch other than {default_branch}"
            + (f" (#{first})" if first else "")
            + "; this carries its work onto it."
        ),
    )
    store.set_pulls(unit_id, (*unit.pulls, Pull(number=number, branch=branch, role=CARRY_ROLE)))
    store.set_merge_record(unit_id, None, None)
    store.set_state(
        unit_id,
        IN_REVIEW,
        pr=number,
        branch=branch,
        note=f"carrying onto {default_branch}",
        cause=Cause.CARRIED,
    )


def _staged(path: Path) -> bool:
    return git(path, "diff", "--cached", "--quiet", check=False).returncode != 0


def _pick_stopped(path: Path) -> bool:
    return git(path, "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD", check=False).returncode == 0


def _pick(
    path: Path,
    sha: str,
    resolve: Resolver | None,
    context: ConflictContext,
    repo_config: RepoConfig | None,
    turn: Turn,
) -> bool:
    """Cherry-pick `sha` in `path`; False when it leaves nothing to commit. A merge commit is
    picked against its first parent."""
    parents = git(path, "rev-list", "--parents", "-n", "1", sha).stdout.split()[1:]
    args = ["cherry-pick", *(["-m", "1"] if len(parents) > 1 else []), sha]
    with turn():
        result = git(path, *args, check=False)
    if result.returncode == 0:
        return True

    def abort(message: str, tried: str = "") -> RestackConflict:
        git(path, "cherry-pick", "--abort", check=False)
        return RestackConflict(message, tried=tried)

    def fail() -> subprocess.CalledProcessError:
        git(path, "cherry-pick", "--abort", check=False)
        return subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)

    if not _pick_stopped(path):
        raise fail()
    patterns = repo_config.generated_paths() if repo_config else ()
    with turn():
        settled, others = take_generated_from_base(path, patterns)
        if not others:
            if _staged(path):
                git(path, "-c", "core.editor=true", "cherry-pick", "--continue")
                return True
            # Stopped as empty: the base already holds what the commit changed.
            git(path, "cherry-pick", "--abort", check=False)
            return False
    if resolve is None:
        with turn():
            raise abort(f"cherry-pick of {sha} conflicts in {', '.join(others)}")
    with turn():
        conflict = read_conflict(
            path,
            result.stdout + result.stderr,
            branch=sha,
            old_base=f"{sha}^1",
            must_keep=None,
            started=sha,
        )
        prompt = conflict_prompt(path, conflict, context, settled) + CARRY_NOTE
    ask_resolver(
        path,
        prompt,
        conflict,
        resolve=resolve,
        context=context,
        turn=turn,
        stop=lambda: git(path, "cherry-pick", "--abort", check=False),
        give_up=abort,
        label=sha,
    )
    with turn():
        # What the conflict touched, and what was already tracked; a stray new file is left out.
        git(path, "add", "-u")
        git(path, "add", "--", *conflict.files)
        finished = git(path, "-c", "core.editor=true", "cherry-pick", "--continue", check=False)
        if finished.returncode != 0:
            raise abort(
                f"the cherry-pick did not complete after resolution:\n"
                f"{finished.stdout}\n{finished.stderr}"
            )
    return True


def carry_held(
    store: UnitStore,
    *,
    repos: dict[str, Path],
    forge_of: Callable[[str], tuple[Forge, RepoId]],
    default_of: Callable[[str], str],
    worktrees: Path,
    claim: events.Claim,
    resolver_for: Callable[[StoredUnit], Resolver | None] = lambda unit: None,
    repo_config_of: Callable[[str], RepoConfig | None] = lambda repo: None,
    turn_of: Callable[[str], Turn] = lambda repo: nullcontext,
    merge_record: events.MergeRecord | None = None,
    resume: events.Resume | None = None,
    log: events.Log = print,
) -> list[str]:
    """The round's carry: first the landing re-check, which records merged each held unit
    whose commit or whose changes are already on the default branch (so a unit that needs no
    carry never gets one), then, for each unit still held `landed_off_default` with no carry,
    `carry` under the unit's branch lease. A unit being built, or whose carry cannot be
    resolved, is left held (the second is noted once and not tried again until its state
    changes). Returns the ids it carried."""
    waiting = resume or (lambda unit, kind, reason, feedback: False)
    events.recheck_landings(
        store, repos=repos, merge_record=merge_record, claim=claim, resume=waiting, log=log
    )
    carried: list[str] = []
    for unit in store.all():
        if not _owed(unit) or unit.repo not in repos or _refused(unit):
            continue
        forge, repo_id = forge_of(unit.repo)
        try:
            with claim(unit):
                if not _owed(store.get(unit.id)):
                    continue
                carry(
                    store,
                    unit.id,
                    forge=forge,
                    repo_id=repo_id,
                    repo=repos[unit.repo],
                    default_branch=default_of(unit.repo),
                    worktrees=worktrees,
                    resolve=resolver_for(unit),
                    repo_config=repo_config_of(unit.repo),
                    turn=turn_of(unit.repo),
                )
        except BranchBusy as error:
            log(f"carry: {unit.id} is being built ({error}) — left for a later round")
            continue
        except RestackConflict as error:
            store.record_event(
                unit.id, CARRY_REFUSED, str(error), cause=Cause.LANDED_OFF_DEFAULT.value
            )
            log(f"{unit.id}: carry abandoned, left held — {error}")
            continue
        log(f"{unit.id}: carried onto {default_of(unit.repo)}")
        carried.append(unit.id)
    return carried


def _owed(unit: StoredUnit) -> bool:
    return unit.state == HELD and unit.cause is Cause.LANDED_OFF_DEFAULT and not is_carrying(unit)


def _refused(unit: StoredUnit) -> bool:
    """The last thing recorded for the unit is a carry that was abandoned."""
    return bool(unit.history) and unit.history[-1].get("event") == CARRY_REFUSED
