"""The policy a confined step runs under, assembled from every place that grants."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.sandboxes.base import SandboxPolicy

# The parts of a repository's git directory a commit writes. Landlock rules only add access,
# so they are granted one at a time and never `hooks` or `config`.
GIT_PARTS = ("objects", "refs", "logs", "packed-refs", "HEAD", "FETCH_HEAD")


class PolicyRefused(ValueError):
    """A grant that would let a step write what a person owns; the message says which and why."""


def build_policy(
    installation: Installation,
    repo: str,
    worktree: Path,
    *,
    runtime: object,
    profile: object,
    local: dict[str, Any] | None = None,
) -> SandboxPolicy:
    """The policy for a step in `worktree` of `repo`: built-ins, then the runtime's and the
    profile's optional `sandbox_paths`, then `repos.<name>.sandbox` and each project's, then
    `local` (the parsed abk.local.yaml)."""
    config = installation.config.repos[repo]
    layers: list[dict[str, Any]] = []
    for source, args in ((runtime, ()), (profile, (worktree,))):
        member = getattr(source, "sandbox_paths", None)
        if member is not None:
            layers.append(member(*args))
    layers.append(config.sandbox.model_dump())
    layers.extend(project.sandbox.model_dump() for project in config.projects)
    layers.append(((local or {}).get("repos", {}).get(repo) or {}).get("sandbox") or {})

    def listed(key: str) -> list[str]:
        return [item for layer in layers for item in layer.get(key, [])]

    write = _resolved(listed("write"), worktree)
    _refuse_owned(listed("write"), write, installation)
    return SandboxPolicy(
        write=_unique([worktree.resolve(), *git_parts(worktree), *write]),
        read=_unique(_resolved(listed("read"), worktree)),
        hosts=_unique(listed("hosts")),
        required=config.sandbox.required,
    )


def git_parts(worktree: Path) -> list[Path]:
    """The git paths a commit in `worktree` writes, derived from its `.git` pointer when it is
    a linked worktree; only those that exist."""
    dot_git = worktree / ".git"
    if dot_git.is_dir():
        common, own = dot_git, None
    elif dot_git.is_file():
        own = _pointed_at(dot_git, worktree)
        pointer = own / "commondir"
        common = (own / pointer.read_text().strip()) if pointer.exists() else own.parent.parent
    else:
        return []
    paths = [common / part for part in GIT_PARTS] + ([own] if own else [])
    return [path.resolve() for path in paths if path.exists()]


def _pointed_at(dot_git: Path, worktree: Path) -> Path:
    text = dot_git.read_text().strip()
    target = text.removeprefix("gitdir:").strip()
    return (worktree / target).resolve()


def _resolved(items: Iterable[str], worktree: Path) -> list[Path]:
    """Each path as one absolute path: `~` expanded, a relative one taken from the worktree,
    `..` and symlinks followed."""
    return [(worktree / Path(item).expanduser()).resolve() for item in items]


def _unique[T](items: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


def _refuse_owned(given: list[str], resolved: list[Path], installation: Installation) -> None:
    """Refuse a write grant of what a person owns, or of a parent that would include it."""
    owned = [
        installation.root / "abk.yaml",
        installation.root / "abk.local.yaml",
        installation.specs_dir,
    ]
    for item, path in zip(given, resolved, strict=True):
        for protected in owned:
            if protected.resolve().is_relative_to(path):
                raise PolicyRefused(
                    f"{item}: refused, it would let a step write {protected}, which a person "
                    "owns in the planning repo"
                )
