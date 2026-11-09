"""Implementations of the orchestration interfaces, found by interface and deployment kind."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType
from typing import Any

from agent_build_kit.installation import Installation

# Modules that register the built-in implementations, imported on the first lookup.
BUILTIN_MODULES: tuple[str, ...] = ()


class Refused(Exception):
    """A lookup that cannot be met, or an implementation whose SDK is not installed."""


def register(interface: str, kind: str, factory: Callable[[Installation], Any]) -> None:
    raise NotImplementedError


def get(interface: str, installation: Installation) -> Any:
    raise NotImplementedError


def names(interface: str) -> list[str]:
    raise NotImplementedError


def import_sdk(extra: str, module: str) -> ModuleType:
    raise NotImplementedError


def reset() -> None:
    raise NotImplementedError
