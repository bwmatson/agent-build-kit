"""The environment section for a repository with a `package.json`.

The manager comes from the manifest's `packageManager` field, then from the
lock file present, then defaults to npm. Syncs are the plain installs, never
the frozen forms: a frozen install fails for exactly the unit that changed a
dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.config import EnvironmentConfig, EnvironmentInputs

MANIFEST = "package.json"
# Lock file by manager, in the order a lock file decides the manager.
LOCKS = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock"}
ARTIFACTS = ["node_modules"]


def read_manifest(root: Path) -> dict:
    """The parsed `package.json` in `root`; empty when it is missing or not an object."""
    try:
        data = json.loads((root / MANIFEST).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _declared(manifest: dict) -> tuple[str, int | None] | None:
    """The manager and major version `packageManager` names, if it names a known one."""
    declared = manifest.get("packageManager")
    if not isinstance(declared, str):
        return None
    name, _, version = declared.partition("@")
    if name not in LOCKS:
        return None
    major = version.split(".", 1)[0]
    return name, int(major) if major.isdigit() else None


def workspace_patterns(manifest: dict) -> list[str]:
    """The `workspaces` patterns of a manifest, in the array or the object form."""
    workspaces = manifest.get("workspaces")
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    if not isinstance(workspaces, list):
        return []
    return [w.removeprefix("./").rstrip("/") for w in workspaces if isinstance(w, str)]


def _check(manager: str, major: int | None) -> list[str]:
    if manager == "pnpm":
        return ["pnpm", "ls", "--depth", "0"]
    if manager == "yarn":
        # `yarn list` is the classic line's; the modern line lists through `info`.
        if major and major >= 2:
            return ["yarn", "info", "--name-only"]
        return ["yarn", "list", "--depth=0"]
    return ["npm", "ls", "--depth=0"]


def detect_environment(root: Path) -> EnvironmentConfig | None:
    """The section for the checkout at `root`, or None without a `package.json`."""
    root = root.expanduser().resolve()
    if not (root / MANIFEST).is_file():
        return None
    manifest = read_manifest(root)
    locks = [name for name in LOCKS.values() if (root / name).is_file()]
    declared = _declared(manifest)
    if declared:
        manager, major = declared
    else:
        manager = next((m for m, name in LOCKS.items() if name in locks), "npm")
        major = None
    dependencies = [MANIFEST, *(f"{w}/{MANIFEST}" for w in workspace_patterns(manifest))]
    return EnvironmentConfig(
        sync=[manager, "install"],
        check=_check(manager, major),
        inputs=EnvironmentInputs(dependencies=dependencies, lock=locks),
        artifacts=list(ARTIFACTS),
    )
