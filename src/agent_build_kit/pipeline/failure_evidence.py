"""The facts kept of the conditions a failing unit-test run ran under (spec: test-failure-evidence).

Three samples feed the bundle `run_log.write_failure_bundle` saves: what the machine was doing,
what the worktree held, and what the run was. Each is a fixed list of facts, never the
environment, and a sample that cannot be taken is left out and not raised. `change_evidence`
builds the section the kit itself (not the agent) appends to a fix change's `design.md`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.orchestration.artifacts import Artifacts
from agent_build_kit.orchestration.local.artifacts import DirectoryArtifacts
from agent_build_kit.pipeline.run_log import bundle_exists, read_bundle_file, run_ledger_path
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.scrub_terms import ROOT_HOME
from agent_build_kit.settings import named_value

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


def first_load(sample: dict[str, object]) -> float | None:
    """The one-minute load average of a machine sample, when it has one."""
    load = sample.get("load")
    return float(load[0]) if isinstance(load, list) and load else None


def load_reading(
    samples: list[dict[str, object]], per_cpu: float
) -> tuple[int | None, bool | None]:
    """The CPU count and whether the host was loaded over the samples of one run: loaded when the
    load of any is at or above `per_cpu` for each CPU. Each is None when the samples do not say
    (no CPU count, or no load)."""
    cpus = next((c for s in samples if isinstance(c := s.get("cpus"), int)), None)
    loads = [load for s in samples if (load := first_load(s)) is not None]
    high = None if not cpus or not loads else any(load >= per_cpu * cpus for load in loads)
    return cpus, high


def load_facts(samples: list[dict[str, object]], per_cpu: float) -> dict[str, object]:
    """`cpus` and `load_high` of `load_reading`, as the conditions of a record keep them."""
    cpus, high = load_reading(samples, per_cpu)
    return {"cpus": cpus, "load_high": high}


def environment_record() -> dict[str, object]:
    """How this process started and what it ran in: its argv, the names (never the values) of
    its environment variables, `HOME`, `TMPDIR`, the first and last entries of `PATH`, and where
    each program a run depends on was found (None for one not found)."""
    path = [entry for entry in named_value("PATH", None).split(os.pathsep) if entry]
    return {
        "argv": list(sys.argv),
        "names": sorted(os.environ),
        "home": named_value("HOME", None) or None,
        "tmpdir": named_value("TMPDIR", None) or None,
        "path_first": path[0] if path else None,
        "path_last": path[-1] if path else None,
        "tools": {tool: shutil.which(tool) for tool in ["git", *profiles.environment_tools()]},
    }


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


EVIDENCE_HEADING = "## Evidence of the first failure"


_HOME_PREFIX = re.compile(rf"{ROOT_HOME}[^/\s\"'`:]+")


def tilde_home(text: str) -> str:
    """`text` with each home directory (`/home/<name>`, `/Users/<name>`) written as `~`, so a
    section that is committed names no user."""
    return _HOME_PREFIX.sub("~", text)


def _ledger_rows(state_dir: Path, unit: str, ran_at: datetime | None) -> list[str]:
    """The rows of the ledger of unit-test runs that are `unit`'s and whose run window (its start
    to its start plus its seconds) holds `ran_at`, the time the failing command began, which is
    later than the start the row records."""
    if ran_at is None:
        return []
    try:
        lines = run_ledger_path(state_dir).read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
            started = datetime.fromisoformat(row["started"])
            ended = started + timedelta(seconds=float(row["seconds"]))
        except (ValueError, KeyError, TypeError):
            continue
        if row.get("unit") == unit and started <= ran_at <= ended:
            rows.append(tilde_home(json.dumps(row, sort_keys=True)))
    return rows


def change_evidence(
    state_dir: Path,
    *,
    unit: str,
    output: str,
    bundle: str,
    ran_at: datetime | None,
    conditions: dict[str, object],
    artifacts: Artifacts | None = None,
) -> str:
    """The section a fix change's `design.md` carries about the first failure: its output, the
    conditions, the ledger rows of the run, and the bundle's path and `machine.json` when the
    failure has a bundle. It stands on its own once the test no longer fails."""
    parts = [
        EVIDENCE_HEADING,
        "",
        "Output of the failing run:",
        "",
        f"```\n{tilde_home(output.strip())}\n```",
    ]
    if conditions:
        shown = tilde_home(json.dumps(conditions, default=str))
        parts += ["", "Conditions:", "", f"```json\n{shown}\n```"]
    rows = _ledger_rows(state_dir, unit, ran_at)
    if rows:
        parts += ["", "Rows of the run in the ledger of unit-test runs:", ""]
        parts += [f"- `{row}`" for row in rows]
    store = artifacts or DirectoryArtifacts(state_dir)
    if bundle and bundle_exists(store, bundle):
        try:
            named = Path(bundle).relative_to(state_dir).as_posix()
        except ValueError:
            named = Path(bundle).name if Path(bundle).is_absolute() else bundle
        parts += ["", f"Bundle of the failing run, under the state directory: `{named}`"]
        machine = (read_bundle_file(store, bundle, "machine.json") or "").strip()
        if machine:
            parts += ["", "What the machine was doing (`machine.json`):", ""]
            parts += [f"```json\n{tilde_home(machine)}\n```"]
    return "\n".join(parts) + "\n"
