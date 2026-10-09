"""A limit on how long a tier 1 command may run.

A test run can finish its tests and then not exit, as when a thread nothing joins keeps
the interpreter alive; the time limit on each test does not see that. A command past
its limit is asked to abort (SIGABRT, so a runtime that can dump the stacks of its
threads does), ended after a short grace if it ignores that, and reported as a failure
that names the command's time and carries the end of its output.
"""

from __future__ import annotations

import os
import signal
import subprocess

TIMED_OUT_EXIT = 124
# How long to wait for the output of a killed group before giving up on a pipe that a
# process outside the group still holds open.
DRAIN_SECONDS = 5


def run_limited(
    args: list[str], *, limit: float, grace: float, **kwargs
) -> subprocess.CompletedProcess:
    """Run `args` in a process group of its own, capturing its output as text.

    Past `limit` seconds the group is sent SIGABRT; past a further `grace` seconds it
    is killed. Either way the result has exit status `TIMED_OUT_EXIT` and its stderr
    ends with a line naming the limit.
    """
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        **kwargs,
    )
    try:
        out, err = process.communicate(timeout=limit)
        return subprocess.CompletedProcess(args, process.returncode, out, err)
    except subprocess.TimeoutExpired:
        pass
    _signal_group(process, signal.SIGABRT)
    try:
        out, err = process.communicate(timeout=grace)
    except subprocess.TimeoutExpired:
        _signal_group(process, signal.SIGKILL)
        out, err = _drain(process)
    note = f"\ntier 1 command timed out after {limit:g} seconds and was aborted\n"
    return subprocess.CompletedProcess(args, TIMED_OUT_EXIT, out or "", (err or "") + note)


def _signal_group(process: subprocess.Popen, number: signal.Signals) -> None:
    try:
        os.killpg(process.pid, number)
    except ProcessLookupError:
        pass


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _drain(process: subprocess.Popen) -> tuple[str, str]:
    """What the killed process printed. A descendant that left the group and still holds
    the pipes would keep the read open for good, so the wait is bounded: past it the
    pipes are closed and what was read so far is returned."""
    try:
        return process.communicate(timeout=DRAIN_SECONDS)
    except subprocess.TimeoutExpired as expired:
        out, err = _text(expired.stdout), _text(expired.stderr)
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            pipe.close()
    process.wait()
    return out, err
