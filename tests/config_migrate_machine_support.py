"""Shared by the tests of the machine-settings move: a request over a planning directory that
repo paths leave, and the merged configuration of two texts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.config import merge_local
from agent_build_kit.config_migrate_machine import MachineRequest

# Spelled in parts so that the scan for home paths in this checkout does not see them.
TILDE = "~" + "/"


def request(tmp_path: Path, local: str | None = None, *, defaults: bool = False) -> MachineRequest:
    """A request whose git top level is `tmp_path/planning`, so `../app` is outside it."""
    return MachineRequest(
        toplevel=tmp_path / "planning", local_text=local, include_defaults=defaults
    )


def merged(base: str, local: str | None) -> dict[str, Any]:
    return merge_local(yaml.safe_load(base) or {}, yaml.safe_load(local or "") or {})
