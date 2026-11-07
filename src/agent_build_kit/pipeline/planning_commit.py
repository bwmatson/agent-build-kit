"""Committing paths of the planning repo and publishing the commit as `planning.publish` says.

The archive of a change and the edit of abk.yaml for a `Project:` line both change the planning
repo from the pipeline, and both must leave it where origin can fast-forward it: a commit that is
made and not published leaves a pipeline worktree ahead of origin, then diverged.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planning_repo import current_branch
from agent_build_kit.pipeline.planning_sync import (
    PlanningMode,
    in_repo_default_branch,
    planning_mode,
)
from agent_build_kit.pipeline.shell import git
from agent_build_kit.tracks.runner import publish_commit


def commit_and_publish(
    inst: Installation,
    paths: Sequence[str],
    *,
    message: str,
    label: str,
    body: str,
    what: str,
    log: Callable[[str], None],
) -> bool:
    """Stage `paths`, commit only them with `message`, and publish the commit under `label`.
    True when a commit was made; False when nothing changed or git refused (logged, naming
    `what`, with git's reason). A rejected push is reported by the publisher and the commit
    stays."""
    staged = git(inst.root, "add", "-A", "--", *paths, check=False)
    if staged.returncode != 0:
        log(f"staging {what} failed:\n{staged.stderr}")
        return False
    if git(inst.root, "diff", "--cached", "--quiet", "--", *paths, check=False).returncode == 0:
        return False
    earlier = git(inst.root, "rev-parse", "HEAD").stdout.strip()
    committed = git(inst.root, "commit", "-q", "-m", message, "--", *paths, check=False)
    if committed.returncode != 0:
        log(f"committing {what} failed:\n{committed.stderr}")
        return False
    if planning_mode(inst) == PlanningMode.PIPELINE_WORKTREE:
        branch = in_repo_default_branch(inst)
    else:
        branch = current_branch(inst.root)
    publish_commit(inst, branch, label, message, earlier, body)
    return True
