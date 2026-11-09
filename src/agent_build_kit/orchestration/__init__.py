"""Implementations of the orchestration interfaces, found by interface and deployment kind.

An implementation registers a factory for an interface and a deployment kind; a lookup for
the installation's kind returns what the factory builds. A pair with nothing registered is
refused, naming the kinds that are, and never falls back to another kind's implementation:
a cloud deployment must not run on local state by accident. Built-in registrations load on
the first use, like the forges.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType
from typing import Any

from agent_build_kit.installation import Installation

# Modules that register the built-in implementations, imported on the first lookup.
BUILTIN_MODULES: tuple[str, ...] = ()

_REGISTRY: dict[str, dict[str, Callable[[Installation], Any]]] = {}
_LOADED = False


class Refused(Exception):
    """A lookup that cannot be met, or an implementation whose SDK is not installed."""


def register(interface: str, kind: str, factory: Callable[[Installation], Any]) -> None:
    """Make `factory` the implementation of `interface` for deployments of `kind`."""
    _REGISTRY.setdefault(interface, {})[kind] = factory


def get(interface: str, installation: Installation) -> Any:
    """The implementation of `interface` for the installation's deployment kind."""
    _load_builtin()
    kind = installation.config.deployment.kind
    factory = _REGISTRY.get(interface, {}).get(kind)
    if factory is None:
        known = ", ".join(names(interface)) or "none"
        raise Refused(
            f"no {kind!r} implementation of {interface!r} is registered "
            f"(registered for: {known}); a {kind} deployment does not fall back to another kind"
        )
    return factory(installation)


def names(interface: str) -> list[str]:
    """The deployment kinds `interface` has an implementation for."""
    _load_builtin()
    return sorted(_REGISTRY.get(interface, {}))


def import_sdk(extra: str, module: str) -> ModuleType:
    """Import `module`, which belongs to the optional `extra`, or refuse naming the extra."""
    try:
        return importlib.import_module(module)
    except ImportError as error:
        raise Refused(
            f"{module} is not installed; it belongs to the {extra!r} extra. "
            f"Install it with: pip install 'agent-build-kit[{extra}]'"
        ) from error


def reset() -> None:
    """Forget every registration, so the built-ins load again on the next lookup."""
    global _LOADED
    _REGISTRY.clear()
    _LOADED = False


def _load_builtin() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for module in BUILTIN_MODULES:
        importlib.import_module(module)
