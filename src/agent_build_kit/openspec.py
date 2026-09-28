"""Running the OpenSpec CLI.

Through `npx --yes @fission-ai/openspec@<pin>` by default: nothing to install
in the planning repo, and the version is a setting (settings.openspec_version)
rather than whatever happens to be on the machine. npx caches the package
after the first run; the only requirement is node on the PATH. An
installation can point `openspec.command` in abk.yaml at something else.

The pipeline calls two subcommands unattended — `validate --all --strict --json`
and `archive <change> --yes` — and `abk init` calls `init`. Everything else
is passed through by `abk openspec -- ...`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit.config import active
from agent_build_kit.settings import settings

PACKAGE = "@fission-ai/openspec"

Run = Callable[..., subprocess.CompletedProcess]


def command() -> list[str]:
    configured = active().openspec.command
    if configured:
        return list(configured)
    return ["npx", "--yes", f"{PACKAGE}@{settings.openspec_version}"]


def run(args: list[str], *, cwd: Path, run: Run | None = None) -> subprocess.CompletedProcess:
    """Run one OpenSpec command in `cwd`, never raising on exit status."""
    runner = run or subprocess.run
    return runner([*command(), *args], cwd=cwd, capture_output=True, text=True, check=False)


def run_ok(args: list[str], *, cwd: Path, run: Run | None = None) -> str:
    """stdout of a command that must succeed, or RuntimeError saying why."""
    result = globals()["run"](args, cwd=cwd, run=run)
    if result.returncode != 0:
        raise RuntimeError(
            f"openspec {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}".strip()
        )
    return result.stdout


def validate(cwd: Path, *, run: Run | None = None) -> subprocess.CompletedProcess:
    return globals()["run"](["validate", "--all", "--strict", "--json"], cwd=cwd, run=run)


def archive(change: str, *, cwd: Path, run: Run | None = None) -> str:
    # --yes because there is nobody to answer a prompt in an unattended run;
    # a conflict still fails rather than being auto-resolved.
    return run_ok(["archive", change, "--yes"], cwd=cwd, run=run)
