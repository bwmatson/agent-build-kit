"""The toolchain profiles a repo can name in abk.yaml."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_build_kit.config import EnvironmentConfig
from agent_build_kit.profiles.base import (
    EnvironmentDrafting,
    ProjectScaffold,
    PromptWords,
    ToolchainProfile,
    is_doc_path,
)

_REGISTRY: dict[str, ToolchainProfile] = {}


def register(profile: ToolchainProfile) -> None:
    _REGISTRY[profile.name] = profile


@contextmanager
def registered(profile: ToolchainProfile) -> Iterator[None]:
    """Register `profile` for the duration of a `with` block, then remove it (a profile of
    the same name registered before is put back). The built-in profiles stay."""
    _load_builtin()
    previous = _REGISTRY.get(profile.name)
    register(profile)
    try:
        yield
    finally:
        if previous is None:
            del _REGISTRY[profile.name]
        else:
            _REGISTRY[profile.name] = previous


def get(name: str) -> ToolchainProfile:
    _load_builtin()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown toolchain profile {name!r} (known: {', '.join(names())})"
        ) from None


def names() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def detect_environment(
    root: Path, *, framework: bool, first: str | None = None
) -> EnvironmentConfig | None:
    """The first environment section a profile proposes for `root`: the profile named
    `first` is asked first, then the rest in registration order. A profile without the
    hook counts as returning None."""
    _load_builtin()
    ordered = [p for p in _REGISTRY.values() if p.name == first]
    ordered += [p for p in _REGISTRY.values() if p.name != first]
    for profile in ordered:
        if not isinstance(profile, EnvironmentDrafting):
            continue
        environment = profile.detect_environment(root, framework=framework)
        if environment is not None:
            return environment
    return None


def scaffold_manifest(profile: str, name: str) -> tuple[str, str] | None:
    """The minimal manifest the named profile writes for a project called `name`, or None
    when the profile has no scaffold."""
    chosen = get(profile)
    if not isinstance(chosen, ProjectScaffold):
        return None
    return chosen.scaffold_manifest(name)


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.profiles import node_npm, python_uv

    register(python_uv.PROFILE)
    register(node_npm.PROFILE)


__all__ = [
    "EnvironmentDrafting",
    "ProjectScaffold",
    "PromptWords",
    "ToolchainProfile",
    "detect_environment",
    "get",
    "is_doc_path",
    "names",
    "register",
    "scaffold_manifest",
    "registered",
]
