"""The Linux backend: Landlock restrictions applied by the launcher to itself before it execs."""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.sandboxes import launcher
from agent_build_kit.sandboxes.base import Availability, Coverage, SandboxPolicy

FIX = "use Linux kernel 5.13 or later with Landlock enabled, or set `required: none` on the repo"

# What the probe's trivial command needs to read.
_PROBE_READ = ("/usr", "/bin", "/lib", "/lib64", "/etc")


def _policy_text(policy: SandboxPolicy) -> str:
    lines = [f"required={policy.required.value}"]
    lines += [f"write={path}" for path in policy.write]
    lines += [f"read={path}" for path in policy.read]
    lines += [f"host={host}" for host in policy.hosts]
    return "\n".join(lines) + "\n"


class Landlock:
    name = "landlock"
    platform = "linux"

    def availability(self) -> Availability:
        """Applies a restriction in a subprocess and checks it held; no file is looked for."""
        with tempfile.TemporaryDirectory(prefix="abk-probe-") as folder:
            probe = Path(folder) / "probe"
            policy = SandboxPolicy(
                write=(),
                read=tuple(Path(path) for path in _PROBE_READ if Path(path).exists()),
                hosts=(),
                required=Coverage.FILES,
            )
            result = subprocess.run(
                self.command(policy, ["sh", "-c", f": > {probe}"]),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            held = result.returncode != 0 and not probe.exists()
        if result.returncode == launcher.EXIT_NOT_APPLIED:
            return Availability(
                ok=False, coverage=Coverage.NONE, cause=result.stderr.strip(), fix=FIX
            )
        if not held:
            return Availability(
                ok=False,
                coverage=Coverage.NONE,
                cause="a Landlock restriction did not stop a write in the probe",
                fix=FIX,
            )
        return Availability(ok=True, coverage=Coverage.FILES)

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        handle, name = tempfile.mkstemp(prefix="abk-sandbox-", suffix=".policy")
        with os.fdopen(handle, "w") as written:
            written.write(_policy_text(policy))
        atexit.register(Path(name).unlink, missing_ok=True)
        script = Path(launcher.__file__).resolve()
        return [sys.executable, "-S", str(script), name, "--", *argv]


BACKEND = Landlock()
