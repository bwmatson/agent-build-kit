"""The toolchain profiles a repo can name in abk.yaml."""

from __future__ import annotations

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


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.profiles import node_npm, python_uv

    register(python_uv.PROFILE)
    register(node_npm.PROFILE)


__all__ = ["PromptWords", "ToolchainProfile", "get", "is_doc_path", "names", "register"]
