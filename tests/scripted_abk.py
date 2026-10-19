"""The real `abk` run as a process on a machine that has only the agents a test installs.

`machine` builds a `PATH` holding links to the few tools `abk init` needs and nothing else, so no
agent installed on the host is found. `install_stand_in` puts a small real agent speaking the
protocol (`tests/runtimes/acp_agent.py`) on that path under a known agent's program name.
`run_abk` runs the command and answers its prompts as they are asked, each by the first rule
whose pattern the output since the last answer matches, so a prompt the host adds or drops
(desktop notifications, say) does not shift the others.

A prompt no rule answers is a failure naming the output so far, never a hang.
"""

from __future__ import annotations

import contextlib
import os
import re
import select
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import Field

from agent_build_kit.model import Frozen
from tests.runtimes.acp_agent import command as agent_command

# What a run of `abk init` needs from the host: the VCS, the OpenSpec CLI's runtime and the
# host CLIs `abk` reads. Nothing else is linked, which is how an installed agent stays out.
TOOLS = ("git", "node", "npx", "npm", "gh", "uv", "env", "sh")

# Seconds without output, from a process still running, before the run is given up as stuck.
SILENCE = 120

Answers = Sequence[tuple[str, str]]


class Machine(Frozen):
    """A `PATH` of its own: `bin_dir` holds links to `TOOLS` and the stand-ins installed."""

    bin_dir: Path
    env: dict[str, str] = Field(repr=False)


class Outcome(Frozen):
    returncode: int
    output: str


def machine(root: Path) -> Machine:
    """A machine under `root` with only `TOOLS` on its path, a home of its own, and no `ABK_`
    setting of this host."""
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    for tool in TOOLS:
        if found := shutil.which(tool):
            (bin_dir / tool).symlink_to(found)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ABK_") and key not in ("GH_TOKEN",)
    }
    env["PATH"] = str(bin_dir)
    # So no agent's configuration on this host is read, only the node package cache is kept.
    cache = env.get("npm_config_cache") or str(Path(env.get("HOME", "~")).expanduser() / ".npm")
    home = root / "home"
    home.mkdir()
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["npm_config_cache"] = cache
    # So a prompt is on the pipe when it is asked, not when a buffer fills.
    env["PYTHONUNBUFFERED"] = "1"
    return Machine(bin_dir=bin_dir, env=env)


def stand_in_command(record: Path, *, models: tuple[str, ...]) -> str:
    """The shell line that starts the stand-in: the protocol test agent recording to `record`
    and offering `models`."""
    return f"exec {shlex.join(agent_command(record, models=models))}"


def install_stand_in(
    on: Machine,
    program: str,
    record: Path,
    *,
    models: tuple[str, ...] = (),
) -> Path:
    """Put the stand-in on the path as `program`, whatever arguments it is started with."""
    path = on.bin_dir / program
    path.write_text(f"#!/bin/sh\n{stand_in_command(record, models=models)}\n")
    path.chmod(0o755)
    return path


def run_abk(on: Machine, args: Sequence[str], *, cwd: Path, answers: Answers = ()) -> Outcome:
    """`abk ARGS` as a process on `on`, its prompts answered by `answers` (pattern, reply)."""
    process = subprocess.Popen(
        [str(Path(sys.executable).parent / "abk"), *args],
        cwd=cwd,
        env=on.env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdin is not None and process.stdout is not None
    seen = ""
    unanswered = ""
    try:
        while True:
            ready, _, _ = select.select([process.stdout], [], [], SILENCE)
            if not ready:
                raise AssertionError(
                    f"abk {' '.join(args)} is waiting at a prompt no answer matches:\n{seen}"
                )
            chunk = os.read(process.stdout.fileno(), 4096).decode(errors="replace")
            if not chunk:
                break
            seen += chunk
            unanswered += chunk
            for pattern, reply in answers:
                if found := re.search(pattern, unanswered):
                    unanswered = unanswered[found.end() :]
                    process.stdin.write(f"{reply}\n".encode())
                    process.stdin.flush()
                    break
        returncode = process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        with contextlib.suppress(BrokenPipeError):
            process.stdin.close()
        process.stdout.close()
    return Outcome(returncode=returncode, output=seen)
