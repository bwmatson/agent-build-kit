"""Moving an abk.yaml from `limits` to `global_limits` and `project_limits` by editing its text
(spec: limits-split-into-global-and-project)."""

from __future__ import annotations

from agent_build_kit.model import Frozen

__all__ = ["ConfigMigrateError", "Migrated", "migrate"]


class ConfigMigrateError(ValueError):
    """The text cannot be migrated as text; the message names the key and the reason."""


class Migrated(Frozen):
    """The new text, and the settings moved to `project_limits` (empty when nothing moved)."""

    text: str
    moved: tuple[str, ...] = ()


def migrate(text: str) -> Migrated:
    raise NotImplementedError
