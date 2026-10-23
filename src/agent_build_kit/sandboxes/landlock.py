"""The Linux backend: Landlock restrictions applied by the launcher to itself before it execs."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.sandboxes import held, launcher
from agent_build_kit.sandboxes.base import Availability, Coverage, SandboxPolicy

FIX = "use Linux kernel 5.13 or later with Landlock enabled, or set `required: none` on the repo"

# What the probe's trivial command needs to read.
_PROBE_READ = ("/usr", "/bin", "/lib", "/lib64", "/etc")


def abi_version() -> int:
    """The Landlock ABI version this kernel reports; the TCP rule needs 4 or later."""
    return launcher.abi_version()


def _policy_text(policy: SandboxPolicy) -> str:
    lines = [f"required={policy.required.value}"]
    lines += [f"write={path}" for path in policy.write]
    lines += [f"read={path}" for path in policy.read]
    lines += [f"host={host}" for host in policy.hosts]
    if policy.proxy_port is not None:
        lines.append(f"proxy_port={policy.proxy_port}")
    return "\n".join(lines) + "\n"


class Landlock:
    name = "landlock"
    platform = "linux"

    def availability(self) -> Availability:
        """Applies a restriction in a subprocess and checks it held; no file is looked for."""
        with held.scene(_PROBE_READ) as (policy, granted):
            failed = held.write_probe(self, policy, granted, FIX)
        if failed:
            return failed
        abi = abi_version()
        if abi < launcher.NETWORK_ABI:
            return Availability(
                ok=True,
                coverage=Coverage.FILES,
                cause=(
                    f"Landlock ABI {abi} cannot confine the network "
                    f"(it needs {launcher.NETWORK_ABI})"
                ),
                fix=FIX,
            )
        return Availability(ok=True, coverage=Coverage.PROCESS)

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        handle, name = tempfile.mkstemp(prefix="abk-sandbox-", suffix=".policy")
        with os.fdopen(handle, "w") as written:
            written.write(_policy_text(policy))
        script = Path(launcher.__file__).resolve()
        return [sys.executable, "-S", str(script), name, "--", *argv]


BACKEND = Landlock()
