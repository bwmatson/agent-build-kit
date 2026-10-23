"""Support for the tests of the Seatbelt backend on a machine that is not a Mac: a `sandbox-exec`
on PATH that speaks the real program's command line, and the platform switched to macOS."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

# `sandbox-exec [-f profile] [-D name=value]... -- command`: the real program's shape. The fake
# copies each profile it is given into `{log}`, then either runs the command unconfined (a
# `sandbox-exec` whose profile does nothing) or refuses to run it.
_SCRIPT = """#!/bin/sh
log={log}
count=0
while [ "$1" != "--" ]; do
  if [ "$1" = "-f" ]; then
    shift
    count=$((count + 1))
    cp "$1" "$log/profile.$$.$count"
  fi
  shift
done
shift
{run}
"""


def as_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")


def no_sandbox_exec(monkeypatch: pytest.MonkeyPatch) -> None:
    """The PATH with every folder that holds a `sandbox-exec` taken out."""
    kept = [
        folder
        for folder in os.environ.get("PATH", "").split(os.pathsep)
        if not (Path(folder) / "sandbox-exec").exists()
    ]
    monkeypatch.setenv("PATH", os.pathsep.join(kept))


def fake_sandbox_exec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, confines: bool) -> Path:
    """Put a fake `sandbox-exec` first on PATH and return the folder holding the profiles it was
    given. With `confines` false it runs the command with nothing denied; with it true it refuses
    to run the command, which leaves a denied write undone."""
    folder = tmp_path / "fake-bin"
    folder.mkdir()
    log = tmp_path / "fake-log"
    log.mkdir()
    program = folder / "sandbox-exec"
    program.write_text(_SCRIPT.format(log=log, run="exit 1" if confines else 'exec "$@"'))
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{folder}:/usr/bin:/bin")
    return log
