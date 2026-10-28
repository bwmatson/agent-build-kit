"""Fakes shared by the tests of the state directory's mount and lock probe."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import lock_probe
from agent_build_kit.pipeline.lock_probe import ProbeResult
from agent_build_kit.pipeline.mounts import Mount


def mount(fstype: str = "ext4", *, source: str = "files:/export", options: str = "rw") -> Mount:
    """A mount of this type; only `ext4` counts as local."""
    return Mount(fstype=fstype, source=source, options=options, local=fstype == "ext4")


class Probes:
    """Counts the probes started, remembers the directories, and answers as a test chooses."""

    def __init__(self) -> None:
        self.count = 0
        self.directories: list[Path] = []
        self.result = ProbeResult(passed=True, detail="ok")

    def __call__(self, directory: Path, *args, **kwargs) -> ProbeResult:
        self.count += 1
        self.directories.append(directory)
        return self.result


def count_probes(monkeypatch: pytest.MonkeyPatch) -> Probes:
    """Replace `probe_locking` with a counting fake."""
    found = Probes()
    monkeypatch.setattr(lock_probe, "probe_locking", found)
    return found
