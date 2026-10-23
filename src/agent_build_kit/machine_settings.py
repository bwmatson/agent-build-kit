"""The settings of an abk.yaml that belong to a machine or a person, as one table that
`abk doctor` and `abk config --migrate` both read (spec: config-migration)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from agent_build_kit.model import Frozen
from agent_build_kit.scrub_terms import ROOT_HOME, TILDE_HOME

__all__ = ["MachineSetting", "holds_home_path", "machine_settings"]


class MachineSetting(Frozen):
    """One setting in a parsed abk.yaml: its key path in document order, why it is listed, and
    its class: a `machine` choice (moved by default) or a fine-to-commit `default`."""

    path: tuple[str, ...]
    reason: str
    kind: Literal["machine", "default"]


_HOME_PATH = re.compile(rf"{TILDE_HOME}|{ROOT_HOME}[A-Za-z]")
_ENV_KEYS = ("file", "value", "argv")


def holds_home_path(value: str) -> bool:
    """Whether a string holds a tilde path, a home-root path or the user's home directory."""
    if _HOME_PATH.search(value):
        return True
    home = str(Path.home())
    return bool(home.rstrip("/")) and bool(re.search(rf"(?<![\w/]){re.escape(home)}(?:/|$)", value))


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _absolute_program(value: object) -> bool:
    return isinstance(value, list) and bool(value) and Path(str(value[0])).is_absolute()


def _outside(value: object, toplevel: Path, root: Path) -> bool:
    resolved = (root / Path(str(value)).expanduser()).resolve()
    return not resolved.is_relative_to(toplevel.resolve())


def _holds_home(value: object) -> bool:
    items = value if isinstance(value, list) else [value]
    return any(isinstance(item, str) and holds_home_path(item) for item in items)


def _classify(
    path: tuple[str, ...], value: object, toplevel: Path, root: Path
) -> tuple[str, Literal["machine", "default"]] | None:
    """The reason and class of the setting at `path`, or None when it is not one."""
    head, last = path[0], path[-1]
    if path == ("project_limits",):
        return ("is the scheduling this machine runs at", "machine") if value else None
    if path == ("planning", "worktree_root"):
        return ("is a directory of this machine", "machine") if value is not None else None
    if head == "repos" and len(path) == 3 and last == "account":
        return (
            ("names the account this machine builds on", "machine") if value is not None else None
        )
    if head == "repos" and len(path) == 3 and last == "path":
        outside = value is not None and _outside(value, toplevel, root)
        return (
            ("leaves the checkout, so it is a place on this machine", "machine")
            if outside
            else None
        )
    if head == "repos" and path[2:4] == ("deploy", "ssh_key") and len(path) == 4:
        return ("is the key file of this machine", "machine") if value is not None else None
    if head == "runtimes" and len(path) == 3:
        if last == "accounts":
            return ("lists the accounts of this person", "machine") if value else None
        if last in ("command", "policy_fix"):
            found = _absolute_program(value)
            return ("starts with an absolute program path", "machine") if found else None
        if last == "limits":
            return ("a plan's thresholds differ per person", "default") if value else None
    in_tests = (len(path) == 2 and head == "tests") or (
        len(path) == 4 and head == "repos" and path[2] == "tests"
    )
    if in_tests:
        if last == "e2e_available":
            return ("is what this machine has", "machine") if value else None
        if last == "e2e_schedule" and str(value).lower() in ("off", "false"):
            return ("a scheduled run switched off suits one machine", "default")
    if last == "hold" and "e2e_splits" in path[:-1] and value is not None:
        return ("a hold may suit one machine", "default")
    if path[:2] == ("verify", "env") and len(path) == 4 and last in _ENV_KEYS:
        if _holds_home(value):
            return ("holds a path under a home directory", "machine")
    return None


def machine_settings(
    document: dict[str, Any], toplevel: Path, root: Path | None = None
) -> list[MachineSetting]:
    """The machine settings of a safe-loaded abk.yaml in the order of the document. `toplevel`
    is the git top level; a `repos.<name>.path` is resolved from `root` (default `toplevel`)."""
    base = root if root is not None else toplevel
    found: list[MachineSetting] = []

    def walk(node: dict[str, Any], path: tuple[str, ...]) -> None:
        for key, value in node.items():
            here = (*path, str(key))
            hit = _classify(here, value, toplevel, base)
            if hit is not None:
                found.append(MachineSetting(path=here, reason=hit[0], kind=hit[1]))
            elif isinstance(value, dict):
                walk(value, here)

    walk(_mapping(document), ())
    return found
