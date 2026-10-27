"""Whether locks taken in a directory exclude a second process."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.mounts import Mount

CACHE_NAME = "state-lock-probe.json"


class ProbeResult(Frozen):
    passed: bool
    detail: str
    fix: str = ""


def probe_locking(
    directory: Path,
    spawn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    mount: Mount | None = None,
) -> ProbeResult:
    """Hold a lock in `directory` and ask a second process for it; `mount` is looked up when
    not given."""
    raise NotImplementedError


def cached_probe(
    local_dir: Path, directory: Path, mount: Mount, *, now: Callable[[], float] | None = None
) -> ProbeResult:
    """A pass cached in `local_dir` for the same mount within a day, else a fresh probe; `now`
    defaults to `time.time`, read from this module's `time`."""
    raise NotImplementedError
