"""The settings of an abk.yaml that belong to a machine or a person, as one table that
`abk doctor` and `abk config --migrate` both read (spec: config-migration)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from agent_build_kit.model import Frozen

__all__ = ["MachineSetting", "holds_home_path", "machine_settings"]


class MachineSetting(Frozen):
    """One setting in a parsed abk.yaml: its key path in document order, why it is listed, and
    its class: a `machine` choice (moved by default) or a fine-to-commit `default`."""

    path: tuple[str, ...]
    reason: str
    kind: Literal["machine", "default"]


def holds_home_path(value: str) -> bool:
    """Whether a string holds `~/`, `/home/<x>` or the user's home directory."""
    raise NotImplementedError


def machine_settings(
    document: dict[str, Any], toplevel: Path, root: Path | None = None
) -> list[MachineSetting]:
    """The machine settings of a safe-loaded abk.yaml in the order of the document. `toplevel`
    is the git top level; a `repos.<name>.path` is resolved from `root` (default `toplevel`)."""
    raise NotImplementedError
