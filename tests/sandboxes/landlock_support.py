"""Support for the tests that apply the real Landlock restrictions in subprocesses."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pytest

import agent_build_kit
from agent_build_kit.sandboxes import Coverage, SandboxBackend, SandboxPolicy
from agent_build_kit.sandboxes.launcher import NETWORK_ABI

# The backends the contract suites run against; a later backend adds its name.
BACKENDS = ["landlock"]

SYSTEM_FOLDERS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/proc")


def readable_folders() -> tuple[Path, ...]:
    """What a confined shell, `cp`, `sed` and the interpreter need to read (and run)."""
    found = [Path(folder) for folder in SYSTEM_FOLDERS]
    found += [
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sys.executable).resolve().parents[1],
        Path(tempfile.gettempdir()),
        Path(agent_build_kit.__file__).resolve().parent,
    ]
    return tuple(dict.fromkeys(path.resolve() for path in found if path.exists()))


def policy_for(
    write: Sequence[Path],
    *,
    read: Sequence[Path] = (),
    required: Coverage = Coverage.FILES,
) -> SandboxPolicy:
    """A policy that grants writes to `write` and reads to the system folders and `read`."""
    return SandboxPolicy(
        write=tuple(path.resolve() for path in write),
        read=(*readable_folders(), *(path.resolve() for path in read)),
        hosts=(),
        required=required,
    )


class Scene:
    """A folder the confined process may write, and a protected one it may only read."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.granted = root / "granted"
        self.protected = root / "protected"
        self.granted.mkdir()
        self.protected.mkdir()
        self.target = self.protected / "file.txt"
        self.target.write_text("original\n")
        self.inside = self.granted / "inside.txt"
        self.inside.write_text("original\n")
        self.movable = self.granted / "movable.txt"
        self.movable.write_text("moved\n")
        self.link = self.granted / "link"
        self.link.symlink_to(self.target)

    def policy(self, *, required: Coverage = Coverage.FILES) -> SandboxPolicy:
        return policy_for([self.granted], read=[self.root], required=required)


def require_working(backend: SandboxBackend) -> None:
    """Skip, with the backend's own cause, where it cannot be applied on this machine."""
    availability = backend.availability()
    if not availability.ok:
        pytest.skip(f"{backend.name} not usable here: {availability.cause} ({availability.fix})")


def require_network_rules(backend: SandboxBackend) -> None:
    """Skip where the kernel cannot confine the network. Landlock's ABI is read from the kernel
    itself, not from `availability()`, which is part of what the tests check."""
    require_working(backend)
    if backend.name == "landlock":
        from agent_build_kit.sandboxes import landlock

        found = landlock.abi_version()
        if found < NETWORK_ABI:
            pytest.skip(f"Landlock ABI {found} has no TCP rule (needs {NETWORK_ABI})")


def run_confined(
    backend: SandboxBackend,
    policy: SandboxPolicy,
    argv: Sequence[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        backend.command(policy, argv),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )


def launcher_args(command: Sequence[str]) -> list[str]:
    """The arguments the launcher gets from a backend's command: `<policy file> -- <argv...>`."""
    return list(command[command.index("--") - 1 :])
