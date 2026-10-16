"""The integration job fetches the pinned OpenSpec CLI once, before its tests
(spec: ci-fetches-openspec-once)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.openspec import PACKAGE
from agent_build_kit.settings import settings
from tests.ci_workflows import WORKFLOWS, ci_jobs

ROOT = WORKFLOWS.parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "warm-openspec.sh"
SCRIPT_PATH = ".github/scripts/warm-openspec.sh"
SPEC = "@example/tool@9.9.9"
ATTEMPTS = 3
MESSAGE = "the OpenSpec CLI is not installed"

# Stands in for npx: keeps the call, notes whether the cache directory was still there,
# fails its first $FAILURES calls, and leaves a cache entry behind as a real fetch does.
FAKE_NPX = """\
#!/bin/sh
{ echo "--- call"; printf '%s\\n' "$@"; } >> "$CALLS"
if [ -d "$npm_config_cache/_npx" ]; then echo stale >> "$STALE"; fi
mkdir -p "$npm_config_cache/_npx/entry"
count=$(cat "$COUNT" 2>/dev/null || echo 0)
echo $((count + 1)) > "$COUNT"
if [ "$count" -lt "$FAILURES" ]; then echo "npm error fetch failed" >&2; exit 1; fi
exit 0
"""


def steps_of(job: str) -> list[dict]:
    return ci_jobs()[job]["steps"]


def warm_steps(job: str) -> list[dict]:
    return [s for s in steps_of(job) if SCRIPT_PATH in s.get("run", "")]


def index_of(steps: list[dict], needle: str, key: str) -> int:
    return next(i for i, s in enumerate(steps) if needle in s.get(key, ""))


class Fetch:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = root / "calls.log"
        self.stale = root / "stale.log"

    def run(self, failures: int, spec: str = SPEC) -> subprocess.CompletedProcess[str]:
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        npx = bin_dir / "npx"
        npx.write_text(FAKE_NPX)
        npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
        home = self.root / "home"
        home.mkdir()
        return subprocess.run(
            ["bash", "-e", str(SCRIPT), spec],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.root,
            env={
                **os.environ,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "HOME": str(home),
                "npm_config_cache": str(home / ".npm"),
                "OPENSPEC_RETRY_DELAY": "0",
                "CALLS": str(self.calls),
                "STALE": str(self.stale),
                "COUNT": str(self.root / "count"),
                "FAILURES": str(failures),
            },
        )

    def calls_made(self) -> list[list[str]]:
        if not self.calls.exists():
            return []
        return [c.splitlines() for c in self.calls.read_text().split("--- call\n")[1:]]

    def stale_calls(self) -> int:
        """How many calls found the previous attempt's cache directory still there."""
        return len(self.stale.read_text().splitlines()) if self.stale.exists() else 0


@pytest.fixture
def fetch(tmp_path: Path) -> Fetch:
    if shutil.which("timeout") is None:
        pytest.skip("the script needs GNU timeout")
    return Fetch(tmp_path)


def test_the_integration_job_warms_openspec_between_uv_setup_and_the_tests() -> None:
    steps = steps_of("integration")
    found = warm_steps("integration")

    assert len(found) == 1
    step = found[0]
    assert "uv run" in step["run"]
    assert "PACKAGE" in step["run"]
    assert "settings.openspec_version" in step["run"]
    assert "timeout-minutes" in step
    uv = index_of(steps, "astral-sh/setup-uv", "uses")
    tests = index_of(steps, "pytest -m integration", "run")
    assert uv < steps.index(step) < tests


def test_neither_the_workflow_nor_the_script_spells_the_pin() -> None:
    assert warm_steps("integration")
    hits = [
        f"{name}:{number}: {line}"
        for name, text in (
            ("ci.yml", (WORKFLOWS / "ci.yml").read_text()),
            (SCRIPT.name, SCRIPT.read_text()),
        )
        for number, line in enumerate(text.splitlines(), 1)
        if PACKAGE in line or settings.openspec_version in line
    ]
    assert hits == []


def test_a_fetch_that_fails_twice_then_succeeds_ends_with_status_0_after_3_calls(
    fetch: Fetch,
) -> None:
    result = fetch.run(failures=2)

    assert result.returncode == 0
    assert len(fetch.calls_made()) == 3
    assert fetch.stale_calls() == 0


def test_a_fetch_that_always_fails_ends_with_status_1_after_3_calls_and_says_so(
    fetch: Fetch,
) -> None:
    result = fetch.run(failures=99)

    assert result.returncode == 1
    assert len(fetch.calls_made()) == ATTEMPTS
    assert MESSAGE in result.stdout + result.stderr
    assert fetch.stale_calls() == 0


def test_the_step_command_prints_the_spec_from_the_kits_settings() -> None:
    (step,) = warm_steps("integration")
    command = step["run"].replace("bash " + SCRIPT_PATH, "echo")

    result = subprocess.run(
        ["bash", "-c", command], capture_output=True, text=True, check=False, cwd=ROOT
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{PACKAGE}@{settings.openspec_version}"


def test_an_empty_spec_is_refused_before_any_npx_call(fetch: Fetch) -> None:
    result = fetch.run(failures=0, spec="")

    assert result.returncode != 0
    assert "usage" in result.stderr
    assert fetch.calls_made() == []


def test_a_fetch_that_succeeds_at_once_is_called_once(fetch: Fetch) -> None:
    result = fetch.run(failures=0)

    assert result.returncode == 0
    assert len(fetch.calls_made()) == 1


def test_each_call_passes_yes_the_spec_and_version(fetch: Fetch) -> None:
    fetch.run(failures=1)

    calls = fetch.calls_made()
    assert len(calls) == 2
    for call in calls:
        assert call == ["--yes", SPEC, "--version"]


def test_the_other_jobs_have_no_warm_up_step() -> None:
    assert warm_steps("integration")
    others = [name for name in ci_jobs() if name != "integration"]

    assert others
    assert all(warm_steps(name) == [] for name in others)


def test_the_test_step_still_runs_pytest_integration_with_no_time_limit_option() -> None:
    assert warm_steps("integration")
    tests = [s for s in steps_of("integration") if "pytest -m integration" in s.get("run", "")]

    assert len(tests) == 1
    run = tests[0]["run"]
    assert run.strip() == "uv run --group dev pytest -m integration"
    assert "timeout" not in run
    assert "time-limit" not in run
