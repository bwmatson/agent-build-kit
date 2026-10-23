"""The policy a confined step runs under, assembled from every place that grants."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent_build_kit import config as config_module
from agent_build_kit import profiles
from agent_build_kit.config import ProjectSandboxConfig, RepoSandboxConfig
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.profiles.base import SandboxPaths
from agent_build_kit.sandboxes.base import (
    SandboxPathsProfile,
    SandboxPathsRuntime,
    SandboxPolicy,
)
from agent_build_kit.sandboxes.proxy import LOCALHOST

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
    entries = policy_entries(installation, repo, worktree, runtime=runtime, profile=profile)

    def listed(key: str) -> list[str]:
        return [e.value for e in entries if e.kind == key]

    write = _resolved(listed("write"), worktree)
    _refuse_owned(listed("write"), write, installation)
    return SandboxPolicy(
        write=_unique([worktree.resolve(), *git_parts(worktree), *write]),
        read=_unique(_resolved(listed("read"), worktree)),
        hosts=_unique(listed("hosts")),
        required=installation.config.repos[repo].sandbox.required,
    )


class PolicyEntry(Frozen):
    """One line of a policy: the list it is in (`read`, `write` or `hosts`), the entry as
    listed and where it came from (`runtime`, a profile name, `abk.yaml` or `abk.local.yaml`)."""

    kind: str
    value: str
    source: str


def policy_entries(
    installation: Installation,
    repo: str,
    worktree: Path,
    *,
    runtime: object,
    profile: object,
) -> list[PolicyEntry]:
    """The entries `build_policy` assembles, each with its source, in the order it takes them:
    the runtime's, the repo's profile's and each project's profile's, then the files'."""
    layers: list[tuple[str, ProjectSandboxConfig]] = []
    if isinstance(runtime, SandboxPathsRuntime):
        layers.append(("runtime", ProjectSandboxConfig.model_validate(runtime.sandbox_paths())))
    seen: set[str] = set()
    toolchains = [profile] + [
        profiles.get(project.profile) for project in installation.config.repos[repo].projects
    ]
    for toolchain in toolchains:
        name = getattr(toolchain, "name", type(toolchain).__name__)
        if name in seen or not isinstance(toolchain, SandboxPathsProfile):
            continue
        seen.add(name)
        layers.append((name, _layer(toolchain.sandbox_paths(worktree))))
    path = installation.root / config_module.CONFIG_FILENAME
    for source, document in (
        (config_module.CONFIG_FILENAME, config_module.read_base(path)),
        (config_module.OVERLAY_FILENAME, config_module.read_overlay(path)),
    ):
        layers.extend((source, block) for block in _blocks(document or {}, repo))
    return [
        PolicyEntry(kind=kind, value=value, source=source)
        for kind in ("write", "read", "hosts")
        for source, layer in layers
        for value in getattr(layer, kind)
    ]


def _layer(given: SandboxPaths | dict[str, list[str]]) -> ProjectSandboxConfig:
    """A profile's answer as a block: the model, or the dict an older profile returns."""
    if isinstance(given, SandboxPaths):
        return ProjectSandboxConfig(
            read=list(given.read), write=list(given.write), hosts=list(given.hosts)
        )
    return ProjectSandboxConfig.model_validate(given)


def proxy_environment(port: int) -> dict[str, str]:
    """The environment that points a step's HTTP clients at the proxy on `port`, and empties
    `NO_PROXY` so no host is reached around it."""
    url = f"http://{LOCALHOST}:{port}"
    pointed = {name: url for key in ("HTTPS_PROXY", "HTTP_PROXY") for name in (key, key.lower())}
    return pointed | {"NO_PROXY": "", "no_proxy": ""}


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
