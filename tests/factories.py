"""Builders the spec_driven tests share.

Nine test files each had their own `unit()` and seven their own `git()`, and
the copies had drifted in their defaults without any test depending on the
difference. A file that does need a different default says so where it
imports these, rather than in a tenth near-copy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.shell import git_out as git
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Unit

__all__ = ["git", "init_repo", "stored_unit", "unit"]

_DEFAULTS: dict[str, Any] = {
    "change": "add-marker",
    "title": "Register the marker",
    "repo": "app",
    "tier": "tier1",
    "depends_on": (),
    "estimated_lines": 140,
    "groups": (1,),
}


def unit(uid: str = "add-marker/1", **overrides) -> Unit:
    fields: dict[str, Any] = {**_DEFAULTS, "id": uid, **overrides}
    return Unit(**fields)


def stored_unit(uid: str = "add-marker/1", **overrides) -> StoredUnit:
    fields: dict[str, Any] = {**_DEFAULTS, "id": uid, **overrides}
    return StoredUnit(**fields)


def init_repo(path: Path) -> Path:
    """An empty repo on `main` with a local identity, so commits work under CI."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@t.t")
    git(path, "config", "user.name", "t")
    return path


def activate_with(**sections):
    """Activate a copy of the active workspace with these top-level sections
    replaced (e.g. git={"push_host": "github-example"})."""
    from agent_build_kit import config as config_module

    current = config_module.active()
    updated = current.model_copy(
        update={
            name: type(getattr(current, name)).model_validate(value)
            for name, value in sections.items()
        }
    )
    config_module.activate(updated, config_module.active_root())
    return updated
