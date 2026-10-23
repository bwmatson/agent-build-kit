"""Support for the tests of the Seatbelt backend on a machine that is not a Mac: a `sandbox-exec`
on PATH that speaks the real program's command line, and the platform switched to macOS."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from typing import Literal

import pytest

# `sandbox-exec [-f profile] [-D name=value]... -- command`: the real program's shape. The fake
# copies each profile it is given into `{log}` as `profile.*` and the script of the `sh -c` it is
# asked to run as `script.*`, then acts as `{run}` says.
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
printf '%s' "$3" > "$log/script.$$"
{run}
"""

# Runs `sh -c <script>` with the write outside the grant failing and the connection probe's
# `nc` replaced by `{connect}`: `false` where the profile stops a direct connection, `true`
# where its network rule is silently ineffective.
_CONFINED = """script=$(printf '%s' "$3" | sed \\
  -e 's#: > [^ ]*outside#false#' -e 's#/usr/bin/nc -z [0-9.]* [0-9]*#{connect}#')
exec "$1" "$2" "$script\""""

# What each fake `sandbox-exec` does with the command it is given.
Mode = Literal["refuses", "unconfined", "leaks_network", "confines"]
_RUN: dict[Mode, str] = {
    "refuses": "exit 1",
    "unconfined": 'exec "$@"',
    "leaks_network": _CONFINED.format(connect="true"),
    "confines": _CONFINED.format(connect="false"),
}


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


def fake_sandbox_exec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: Mode) -> Path:
    """Put a fake `sandbox-exec` first on PATH and return the folder holding the profiles and
    scripts it was given. `unconfined` runs the command with nothing denied; `refuses` does not
    run it; `leaks_network` denies only the write outside the grant, as a profile whose network
    rule is silently ineffective does; `confines` denies the write and the direct connection, as
    a working Seatbelt does."""
    folder = tmp_path / "fake-bin"
    folder.mkdir()
    log = tmp_path / "fake-log"
    log.mkdir()
    program = folder / "sandbox-exec"
    program.write_text(_SCRIPT.format(log=log, run=_RUN[mode]))
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{folder}:/usr/bin:/bin")
    return log
