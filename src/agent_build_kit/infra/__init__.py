"""The infrastructure profiles a repo can name in abk.yaml."""

from __future__ import annotations

from agent_build_kit.infra.base import InfraProfile

_REGISTRY: dict[str, InfraProfile] = {}


def register(profile: InfraProfile) -> None:
    _REGISTRY[profile.name] = profile


def get(name: str) -> InfraProfile:
    _load_builtin()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown infrastructure profile {name!r} (known: {', '.join(names())})"
        ) from None


def names() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def profiles() -> list[InfraProfile]:
    """Every registered profile, by name."""
    return [get(name) for name in names()]


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.infra import docker, none

    register(docker.PROFILE)
    register(none.PROFILE)


__all__ = ["InfraProfile", "get", "names", "profiles", "register"]
