"""The facts kept of the conditions a failing unit-test run ran under (spec: test-failure-evidence).

Three samples feed the bundle `run_log.write_failure_bundle` saves: what the machine was doing,
what the worktree held, and what the run was. Each is a fixed list of facts, never the
environment, and a sample that cannot be taken is left out and not raised.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit.profiles.base import ToolchainProfile

# The most entries a listing in a bundle holds.
LISTING_CAP = 5000
# Directories no listing of the worktree's tests descends into.
_SKIPPED = frozenset(["node_modules", "__pycache__"])

Run = Callable[..., subprocess.CompletedProcess]


def probe_output(run: Run, where: Path, probe: list[str]) -> str:
    """What `probe`, a profile's version query, prints (both streams) run in `where`; empty when
    it cannot run."""
    try:
        result = run(probe, cwd=where)
    except OSError:
        return ""
    return f"{result.stdout}\n{result.stderr}"


def machine_sample() -> dict[str, object]:
    """The load averages and the memory free now."""
    sample: dict[str, object] = {}
    try:
        sample["load"] = list(os.getloadavg())
    except OSError:
        pass
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                sample["memory_available_kb"] = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    sample["cpus"] = os.cpu_count()
    return sample


def _git(run: Run, where: Path, *args: str) -> str:
    try:
        result = run(["git", *args], cwd=where)
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def worktree_state(run: Run, where: Path, toolchain: ToolchainProfile) -> dict[str, object]:
    """`git status --porcelain` and the test files under `where`, each capped."""
    tests: list[str] = []
    for folder, names, files in os.walk(where):
        names[:] = [n for n in names if not n.startswith(".") and n not in _SKIPPED]
        for file in files:
            relative = (Path(folder) / file).relative_to(where).as_posix()
            if toolchain.is_test_path(relative):
                tests.append(relative)
    return {
        "status": _git(run, where, "status", "--porcelain").splitlines()[:LISTING_CAP],
        "tests": sorted(tests)[:LISTING_CAP],
    }


def _tests(state: dict[str, object]) -> set[str]:
    listed = state.get("tests")
    return {str(name) for name in listed} if isinstance(listed, list) else set()


def worktree_changes(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    """The `before` and `after` states with the test files that vanished and appeared."""
    was = _tests(before)
    now = _tests(after)
    return {
        "before": before,
        "after": after,
        "vanished": sorted(was - now),
        "appeared": sorted(now - was),
    }


def shas(run: Run, where: Path, base: str) -> dict[str, str]:
    """The commits `base` and HEAD name."""
    return {
        "base": _git(run, where, "rev-parse", base).strip(),
        "head": _git(run, where, "rev-parse", "HEAD").strip(),
    }
