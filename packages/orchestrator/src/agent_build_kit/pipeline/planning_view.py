"""The `.planning` link: the pipeline's state, browsable from the folder the editor has open."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import append_missing_lines
from agent_build_kit.pipeline.planning_repo import common_dir, main_working_tree, toplevel
from agent_build_kit.pipeline.planning_sync import in_repo_name
from agent_build_kit.pipeline.shell import git_out

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation

LINK_NAME = ".planning"
_WOULD = {"created": "create", "repointed": "repoint"}


class PlanningViewRefused(Exception):
    """`.planning` is something `ensure_view` must not replace."""


def _target(link: Path) -> Path:
    return Path(os.path.normpath(link.parent / os.readlink(link)))


def _exclude_line(root: Path) -> str:
    top = toplevel(root)
    relative = root.resolve().relative_to(top) if top is not None else Path()
    return "/" + (relative / LINK_NAME).as_posix()


def ensure_view(root: Path, state: Path, *, dry_run: bool = False) -> str:
    """Make `state` and the link `<root>/.planning` to it, with its `info/exclude` line; what it
    did: `created`, `repointed`, `unchanged`, or `would ...` under `dry_run`."""
    link = root / LINK_NAME
    done = "created"
    if link.is_symlink():
        if _target(link) == state:
            done = "unchanged"
        elif link.exists():
            raise PlanningViewRefused(
                f"{LINK_NAME} is a link to {_target(link)}, not to {state}; remove it to let "
                "abk init replace it"
            )
        else:
            done = "repointed"
    elif link.exists():
        raise PlanningViewRefused(
            f"{LINK_NAME} is a file or directory in {root}; move it so abk init can link the state"
        )
    if dry_run:
        return done if done == "unchanged" else f"would {_WOULD[done]}"
    state.mkdir(parents=True, exist_ok=True)
    if done != "unchanged":
        link.unlink(missing_ok=True)
        link.symlink_to(state)
    exclude = Path(
        git_out(root, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    )
    append_missing_lines(exclude, [_exclude_line(root)])
    return done


def view_problem(root: Path, state: Path) -> str | None:
    """None when `<root>/.planning` links to `state`, else a one-line description of what it is."""
    link = root / LINK_NAME
    if link.is_symlink():
        target = _target(link)
        if not link.exists():
            return "dangling"
        return None if target == state else f"points to {target}"
    return "a file or directory" if link.exists() else "missing"


def state_inside_repo(state: Path, repo_top: Path, git_dir: Path) -> Path | None:
    """The real path of `state` when it is the repository's working tree or git directory or
    inside either, else None."""
    real = state.resolve()
    inside = any(real.is_relative_to(base.resolve()) for base in (repo_top, git_dir))
    return real if inside else None


class WorkingCopyView(Frozen):
    """The working copy's `.planning` link and what is wrong with it (None when it is right)."""

    link: Path
    problem: str | None


def installation_state_inside_repo(inst: Installation) -> Path | None:
    """`state_inside_repo` for an in-repo installation's state directory; None when it is outside
    the repository, or the installation is not in-repo or not in a repository."""
    common = common_dir(inst.root)
    if in_repo_name(inst) is None or common is None:
        return None
    return state_inside_repo(inst.state_dir, main_working_tree(inst.root) or inst.root, common)


def working_copy_view(inst: Installation) -> WorkingCopyView | None:
    """The link `abk init` makes in the working copy, for an in-repo installation whose state
    directory is outside the repository; None when there is no link to check (a separate planning
    repo, or a state inside the repository, which the state location check reports)."""
    if in_repo_name(inst) is None or installation_state_inside_repo(inst) is not None:
        return None
    root = main_working_tree(inst.root) or inst.root
    return WorkingCopyView(link=root / LINK_NAME, problem=view_problem(root, inst.state_dir))
