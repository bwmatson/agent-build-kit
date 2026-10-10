"""The toolchain profiles a repo can name in abk.yaml."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import EnvironmentConfig
from agent_build_kit.profiles.base import PromptWords, ToolchainProfile, is_doc_path

_REGISTRY: dict[str, ToolchainProfile] = {}


def register(profile: ToolchainProfile) -> None:
    _REGISTRY[profile.name] = profile


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
        hook = getattr(profile, "detect_environment", None)
        environment = hook(root, framework=framework) if hook else None
        if environment is not None:
            return environment
    return None


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.profiles import node_npm, python_uv

    register(python_uv.PROFILE)
    register(node_npm.PROFILE)


__all__ = [
    "PromptWords",
    "ToolchainProfile",
    "detect_environment",
    "get",
    "is_doc_path",
    "names",
    "register",
]
