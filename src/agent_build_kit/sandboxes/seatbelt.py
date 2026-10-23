"""The macOS backend: a Seatbelt profile generated from the policy, run through `sandbox-exec`."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.sandboxes import held
from agent_build_kit.sandboxes.base import Availability, Coverage, SandboxPolicy

FIX = (
    "run on macOS, where `sandbox-exec` ships with the system, or set `required: none` on the repo"
)

# What the probes' trivial commands need to read.
_PROBE_READ = ("/usr", "/bin", "/sbin", "/System", "/Library", "/private/etc", "/dev")

# What any confined command needs beyond the policy's lists: to start, to look paths up, to read
# the device folder and to write the few device files shells use.
_BASE_RULES = (
    "(allow process-exec)",
    "(allow process-fork)",
    "(allow sysctl-read)",
    "(allow mach-lookup)",
    "(allow signal (target same-sandbox))",
    "(allow file-read-metadata)",
    '(allow file-read* (subpath "/dev"))',
    '(allow file-write* (regex #"^/dev/(null|zero|tty|dtracehelper|fd/[0-9]+)$"))',
)


def _entries(policy: SandboxPolicy) -> list[tuple[str, str, Path]]:
    """The (parameter name, `subpath` or `literal`, path) of each folder or file in the policy."""
    found = [(f"WRITE_{at}", path) for at, path in enumerate(policy.write)]
    found += [(f"READ_{at}", path) for at, path in enumerate(policy.read)]
    return [(name, "literal" if path.is_file() else "subpath", path) for name, path in found]


def _rule(operations: str, entries: list[tuple[str, str, Path]]) -> list[str]:
    return [f'(allow {operations} ({kind} (param "{name}")))' for name, kind, _ in entries]


def profile_text(policy: SandboxPolicy) -> str:
    """The Seatbelt profile for `policy`; paths are `(param "NAME")` references, never literals."""
    entries = _entries(policy)
    writes = [entry for entry in entries if entry[0].startswith("WRITE_")]
    lines = ["(version 1)", "(deny default)", *_BASE_RULES]
    lines += _rule("file-write*", writes)
    # What may be written may be read.
    lines += _rule("file-read*", entries)
    if policy.proxy_port is not None:
        lines.append(f'(allow network-outbound (remote ip "localhost:{policy.proxy_port}"))')
    return "\n".join(lines) + "\n"


class Seatbelt:
    name = "seatbelt"
    platform = "darwin"

    def availability(self) -> Availability:
        """Runs two restricted commands and checks a denied write and a direct connection both
        failed; the binary being present proves nothing."""
        if not sys.platform.startswith(self.platform):
            return _failed(f"Seatbelt needs macOS; this machine is {sys.platform}")
        if shutil.which("sandbox-exec") is None:
            return _failed("`sandbox-exec` was not found on PATH")
        with held.scene(_PROBE_READ) as (policy, granted):
            written = held.write_probe(self, policy, granted, FIX)
            with socket.socket() as server:
                server.bind(("127.0.0.1", 0))
                server.listen(1)
                connected = self._connect_probe(policy, granted, server.getsockname()[1])
        return written or connected or Availability(ok=True, coverage=Coverage.PROCESS)

    def _connect_probe(
        self, policy: SandboxPolicy, granted: Path, port: int
    ) -> Availability | None:
        """None when the command ran and a direct connection to a listening port failed."""
        ran, connected = granted / "ran-connect", granted / "connected"
        try:
            result = held.run(
                self, policy, f"/usr/bin/nc -z 127.0.0.1 {port} && : > {connected}; : > {ran}"
            )
        except subprocess.TimeoutExpired:
            return held.timed_out(self, FIX)
        if connected.exists():
            return _failed("a Seatbelt profile did not stop a direct connection in the probe")
        if not ran.exists():
            return _failed(result.stderr.strip() or "the probe command did not run under Seatbelt")
        return None

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        handle, name = tempfile.mkstemp(prefix="abk-sandbox-", suffix=".sb")
        with os.fdopen(handle, "w") as written:
            written.write(profile_text(policy))
        params = [part for entry in _entries(policy) for part in ("-D", f"{entry[0]}={entry[2]}")]
        return ["sandbox-exec", "-f", name, *params, "--", *argv]


def _failed(cause: str) -> Availability:
    return held.failed(cause, FIX)


BACKEND = Seatbelt()
