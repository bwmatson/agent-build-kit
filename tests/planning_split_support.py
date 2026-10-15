"""On-disk installations and a driver for `abk planning split`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_build_kit.cli import main
from agent_build_kit.init.scaffold import RULES_HEADER
from agent_build_kit.installation import Installation, load_installation

__all__ = ["load", "split", "write_installation"]

DEFAULT_REPOS: Mapping[str, Sequence[str]] = {"app": ("lib",), "lib": ()}


def write_installation(
    root: Path,
    repos: Mapping[str, Sequence[str]] = DEFAULT_REPOS,
    *,
    stamp: bool = True,
    state: bool = True,
) -> Path:
    """A planning root `abk.yaml` loads from: `repos` maps a repo to the repos it consumes."""
    lines = ["repos:"]
    for name, consumes in repos.items():
        checkout = root / "checkouts" / name
        checkout.mkdir(parents=True, exist_ok=True)
        lines += [f"  {name}:", f"    path: {checkout}", f"    slug: example/{name}"]
        if consumes:
            lines += ["    consumes:", *(f"      - {other}" for other in consumes)]
    config = root / "abk.yaml"
    config.write_text("\n".join(lines) + "\n")
    (root / "openspec").mkdir(exist_ok=True)
    (root / "openspec" / "config.yaml").write_text(
        f"{RULES_HEADER}\n" if stamp else "schema: spec-driven\n"
    )
    if state:
        (root / "runs").mkdir(exist_ok=True)
        (root / "runs" / "units.json").write_text('{"units": []}\n')
    return config


def load(root: Path) -> Installation:
    return load_installation(root / "abk.yaml")


def split(source: Path, *argv: str) -> int:
    """`abk planning split` in process; an argparse refusal is its exit code, 2."""
    try:
        return main(["--config", str(source / "abk.yaml"), "planning", "split", *argv])
    except SystemExit as stop:
        return int(stop.code or 0)
