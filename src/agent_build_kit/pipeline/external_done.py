"""Recording a hand merge of held work (spec: external-work)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.external_file import HoldRefused, done_groups, record_done
from agent_build_kit.pipeline.planning_repo import default_branch_of
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.task_progress import mark_groups
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import MERGED, PLANNED
from agent_build_kit.pipeline.wiring import is_ancestor

NOTE = "recorded by hand"


class HandMergeRefused(ValueError):
    """A hand merge that cannot be recorded; the message says why."""


def _merge_commit(inst: Installation, repo: str, pr: int | None, commit: str | None) -> str:
    """The verified commit of a hand merge, or `HandMergeRefused` saying why not."""
    if (pr is None) == (commit is None):
        raise HandMergeRefused("give either a pull request number or a commit")
    if pr is not None:
        forge, repo_id = inst.forge_of(repo)
        merged = forge.merge_commit(repo_id, pr)
        if not merged:
            raise HandMergeRefused(f"pull request #{pr} is not merged")
        return merged
    assert commit is not None
    checkout = inst.repo(repo).path
    git(checkout, "fetch", "-q", "origin", check=False)
    trunk = default_branch_of(checkout)
    remote = f"origin/{trunk}"
    known = git(checkout, "rev-parse", "-q", "--verify", remote, check=False).returncode == 0
    tip = remote if known else trunk
    if not is_ancestor(checkout, commit, tip):
        raise HandMergeRefused(f"commit {commit} is not on the default branch ({trunk})")
    return git(checkout, "rev-parse", commit).stdout.strip()


def record_hand_merge(
    inst: Installation,
    store: UnitStore,
    change: str,
    groups: Sequence[int],
    *,
    pr: int | None = None,
    commit: str | None = None,
) -> None:
    """Verify the pull request `pr` is merged, or `commit` is on the repo's default branch, then
    record `groups` of `change` as built by hand. Raises `HandMergeRefused` otherwise."""
    wanted = set(groups)
    units: list[StoredUnit] = [
        unit
        for unit in store.all()
        if unit.state == PLANNED
        and any(m.change == change and wanted & set(m.groups) for m in unit.members())
    ]
    if not units:
        raise HandMergeRefused(f"no planned unit carries groups {sorted(wanted)} of {change}")
    repos = sorted({unit.repo for unit in units})
    if len(repos) > 1:
        numbers = ", ".join(str(group) for group in sorted(wanted))
        raise HandMergeRefused(
            f"groups {numbers} of {change} are in more than one repo ({', '.join(repos)}): "
            "record each repo's merge separately"
        )
    sha = _merge_commit(inst, repos[0], pr, commit)
    change_dir = inst.changes_dir / change
    try:
        record_done(
            change_dir, groups, merged_by=str(pr) if pr is not None else sha, at=datetime.now(UTC)
        )
    except HoldRefused as error:
        raise HandMergeRefused(str(error)) from error
    mark_groups(change_dir / "tasks.md", groups, done=True)
    for unit in units:
        if all(set(m.groups) <= done_groups(inst.changes_dir / m.change) for m in unit.members()):
            store.set_merge_record(unit.id, sha, None)
            store.set_state(unit.id, MERGED, note=NOTE, cause=Cause.MERGED)
