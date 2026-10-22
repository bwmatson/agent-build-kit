"""The policy a confined step runs under, assembled from every place that grants."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent_build_kit import config as config_module
from agent_build_kit.config import ProjectSandboxConfig, RepoSandboxConfig
from agent_build_kit.installation import Installation
from agent_build_kit.sandboxes.base import (
    SandboxPathsProfile,
    SandboxPathsRuntime,
    SandboxPolicy,
)

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
) -> SandboxPolicy:
    """The policy for a step in `worktree` of `repo`: built-ins, then the runtime's and the
    profile's optional `sandbox_paths`, then `repos.<name>.sandbox` and each project's from
    abk.yaml, then the same keys from abk.local.yaml. The two files are read apart: the loaded
    configuration holds the overlay laid over the committed file, which replaces a list whole."""
    layers: list[ProjectSandboxConfig] = []
    if isinstance(runtime, SandboxPathsRuntime):
        layers.append(ProjectSandboxConfig.model_validate(runtime.sandbox_paths()))
    if isinstance(profile, SandboxPathsProfile):
        layers.append(ProjectSandboxConfig.model_validate(profile.sandbox_paths(worktree)))
    path = installation.root / config_module.CONFIG_FILENAME
    for document in (config_module.read_base(path), config_module.read_overlay(path)):
        layers.extend(_blocks(document or {}, repo))

    def listed(key: str) -> list[str]:
        return [item for layer in layers for item in getattr(layer, key)]

    write = _resolved(listed("write"), worktree)
    _refuse_owned(listed("write"), write, installation)
    return SandboxPolicy(
        write=_unique([worktree.resolve(), *git_parts(worktree), *write]),
        read=_unique(_resolved(listed("read"), worktree)),
        hosts=_unique(listed("hosts")),
        required=installation.config.repos[repo].sandbox.required,
    )


def _blocks(document: dict[str, Any], repo: str) -> list[ProjectSandboxConfig]:
    """The repo's sandbox block in one file and then each of its projects', validated."""
    entry = (document.get("repos") or {}).get(repo) or {}
    blocks: list[ProjectSandboxConfig] = [
        RepoSandboxConfig.model_validate(entry.get("sandbox") or {})
    ]
    for project in entry.get("projects") or []:
        blocks.append(ProjectSandboxConfig.model_validate(project.get("sandbox") or {}))
    return blocks


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
    """Refuse a write grant of what a person owns: the file itself, a parent that would
    include it, and anything inside the specs folder."""
    specs = installation.specs_dir.resolve()
    owned = [
        installation.root / config_module.CONFIG_FILENAME,
        installation.root / config_module.OVERLAY_FILENAME,
        specs,
    ]
    for item, path in zip(given, resolved, strict=True):
        reached = [p for p in owned if p.resolve().is_relative_to(path)]
        if path.is_relative_to(specs):
            reached.append(specs)
        if reached:
            raise PolicyRefused(
                f"{item}: refused, it would let a step write {reached[0]}, which a person "
                "owns in the planning repo"
            )
