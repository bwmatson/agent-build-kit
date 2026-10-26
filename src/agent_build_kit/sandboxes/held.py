"""The write probe every backend's `availability()` runs: apply a restriction in a subprocess and
check it held, so a backend is judged by what it did and not by what is installed."""

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from agent_build_kit.sandboxes.base import Availability, Coverage, SandboxBackend, SandboxPolicy

TIMEOUT = 30


@contextmanager
def scene(read: Sequence[str]) -> Iterator[tuple[SandboxPolicy, Path]]:
    """A policy that grants a scratch folder for writes and the `read` folders that exist, and
    that folder."""
    with tempfile.TemporaryDirectory(prefix="abk-probe-") as folder:
        granted = Path(folder).resolve() / "granted"
        granted.mkdir()
        policy = SandboxPolicy(
            write=(granted,),
            read=tuple(Path(path) for path in read if Path(path).exists()),
            hosts=(),
            required=Coverage.FILES,
        )
        yield policy, granted


def run(
    backend: SandboxBackend, policy: SandboxPolicy, script: str
) -> subprocess.CompletedProcess[str]:
    """Run `script` in `sh` under the backend's restrictions; raises `TimeoutExpired`."""
    return subprocess.run(
        backend.command(policy, ["sh", "-c", script]),
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
        check=False,
    )


def run_replacing(
    backend: SandboxBackend,
    policy: SandboxPolicy,
    script: str,
    *,
    ready: Path,
    replace: Callable[[], None],
) -> subprocess.CompletedProcess[str]:
    """Run `script` as `run` does and, when it creates `ready` (the step is waiting), call
    `replace` from outside the step; the script goes on once it has. Raises `TimeoutExpired`."""
    step = subprocess.Popen(
        backend.command(policy, ["sh", "-c", script]),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + TIMEOUT
    try:
        while step.poll() is None and not ready.exists():
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(script, TIMEOUT)
            time.sleep(0.02)
        if step.poll() is None:
            replace()
        out, err = step.communicate(timeout=max(deadline - time.monotonic(), 1))
    except BaseException:
        # Whatever went wrong, no step is left waiting for a file that will not come.
        step.kill()
        step.communicate()
        raise
    return subprocess.CompletedProcess(step.args, step.returncode, out, err)


def failed(cause: str, fix: str) -> Availability:
    """What a backend answers when its probe did not hold: not ok, nothing confined, and why."""
    return Availability(ok=False, coverage=Coverage.NONE, cause=cause, fix=fix)


def timed_out(backend: SandboxBackend, fix: str) -> Availability:
    """The not-ok answer for a probe that did not finish within `TIMEOUT` seconds."""
    return failed(f"the {backend.name} probe did not finish in {TIMEOUT} seconds", fix)


def write_probe(
    backend: SandboxBackend, policy: SandboxPolicy, granted: Path, fix: str
) -> Availability | None:
    """None when a command ran under the restriction, the granted write happened and the
    ungranted one did not; otherwise a not-ok `Availability` with the cause and `fix`."""
    ran, outside = granted / "ran", granted.parent / "outside"
    try:
        result = run(backend, policy, f": > {ran}; : > {outside}")
    except subprocess.TimeoutExpired:
        return timed_out(backend, fix)
    # Only a command that ran under the restriction proves it held: the granted write happened
    # and the ungranted one did not.
    if result.returncode != 0 and ran.exists() and not outside.exists():
        return None
    cause = (
        result.stderr.strip() or f"a {backend.name} restriction did not stop a write in the probe"
    )
    return failed(cause, fix)
