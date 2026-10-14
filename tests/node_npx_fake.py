"""A project directory in which `npx` is a program that records the arguments it was given,
one per line, and, when told where to write a JUnit report with `--outputFile`, writes a
recorded Vitest report there and exits as a red run does. The node profile's commands run
for real against it."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

VITEST = Path(__file__).resolve().parent / "fixtures" / "external" / "vitest"

FAKE_NPX = """\
#!/bin/sh
# Stands in for npx: keeps the call, writes the recorded report where it is told to.
{ echo "--- call"; printf '%s\\n' "$@"; } >> "$CALLS"
for arg in "$@"; do
  case "$arg" in
    --outputFile=*) cp "$RECORDING" "${arg#*=}"; exit 1 ;;
  esac
done
exit "${FAIL_TOOL_EXIT:-0}"
"""


class Project:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = root / "calls.log"
        self.scratch = root / "scratch"

    def run(
        self, command: str, recording: str = "assertion", **env: str
    ) -> subprocess.CompletedProcess[str]:
        """`command` in the project, `npx` writing the report recorded as `recording`."""
        return subprocess.run(
            command,
            shell=True,
            cwd=self.root / "project",
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
                "TMPDIR": str(self.scratch),
                "CALLS": str(self.calls),
                "RECORDING": str(VITEST / f"{recording}.xml"),
                **env,
            },
        )

    def calls_made(self) -> list[list[str]]:
        """The argument lists `npx` was called with, in order."""
        if not self.calls.exists():
            return []
        chunks = self.calls.read_text().split("--- call\n")[1:]
        return [chunk.splitlines() for chunk in chunks]


def make_project(root: Path) -> Project:
    (root / "bin").mkdir()
    npx = root / "bin" / "npx"
    npx.write_text(FAKE_NPX)
    npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
    (root / "project").mkdir()
    (root / "scratch").mkdir()
    return Project(root)
