"""`abk e2e-test check` over dimensions: a test with two values of one dimension and a marker
the runner does not register are findings, a clean repo has none, and a marker declared twice
is named (spec: e2e-dimensions)."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import e2e_cmd
from agent_build_kit.config import E2eDimensionValue
from agent_build_kit.pipeline.e2e_exclusive import check_dimensions
from agent_build_kit.profiles.python_uv import PROFILE
from tests.e2e_check_support import installation

DIMENSIONS = {
    "runtime": {
        "claude_code": {"marker": "runtime_claude_code"},
        "acp": {"marker": "runtime_acp"},
    },
    "telemetry": {"otel": {"marker": "telemetry_otel"}, "local": {"marker": "telemetry_local"}},
}
REGISTERED = (
    "local_stack",
    "runtime_claude_code",
    "runtime_acp",
    "telemetry_otel",
    "telemetry_local",
)
LIVE = "tests/integration/test_live.py::"
CLEAN = {
    f"{LIVE}test_runtime_neutral[claude_code]": {"local_stack", "runtime_claude_code"},
    f"{LIVE}test_runtime_neutral[acp]": {"local_stack", "runtime_acp"},
    f"{LIVE}test_sink": {"local_stack", "runtime_acp", "telemetry_otel"},
    f"{LIVE}test_plain": {"local_stack"},
}


class _Carries(dict):
    """The names a `-m` expression is evaluated over: true for a marker the test carries."""

    def __init__(self, carried: set[str]) -> None:
        super().__init__()
        self.carried = carried

    def __missing__(self, name: str) -> bool:
        return name in self.carried


class Runner:
    """Stands in for the process run: answers `--markers` with the registered markers and a
    collection by evaluating the `-m` expression over the markers each test carries."""

    def __init__(
        self, tests: Mapping[str, set[str]], registered: tuple[str, ...] = REGISTERED
    ) -> None:
        self.tests = tests
        self.registered = registered

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        assert "--collect-only" in argv or "--markers" in argv, f"ran a test: {argv}"
        if "--markers" in argv:
            out = "".join(f"@pytest.mark.{name}: {name}\n\n" for name in self.registered)
            return subprocess.CompletedProcess(argv, 0, out, "")
        expression = argv[argv.index("-m") + 1]
        found = [
            test
            for test, carried in self.tests.items()
            if eval(expression, {}, _Carries(carried))  # noqa: S307
        ]
        return subprocess.CompletedProcess(argv, 0 if found else 5, "\n".join(found) + "\n", "")


def check(
    tmp_path: Path, run: Runner, capsys: pytest.CaptureFixture[str]
) -> tuple[int, list[str]]:
    found = installation(tmp_path, splits=None, dimensions=DIMENSIONS)
    capsys.readouterr()
    code = e2e_cmd.cmd_e2e_check(argparse.Namespace(repo="app"), found, run=run)
    shown = capsys.readouterr()
    return code, (shown.out + shown.err).splitlines()


def test_a_repo_with_each_test_carrying_at_most_one_value_per_dimension_has_no_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = check(tmp_path, Runner(CLEAN), capsys)

    assert code == 0
    assert not [line for line in lines if "finding" in line]
    assert any("runtime" in line for line in lines)


def test_a_test_with_two_values_of_one_dimension_is_named_with_the_dimension_and_the_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    both = {**CLEAN, f"{LIVE}test_both": {"local_stack", "runtime_claude_code", "runtime_acp"}}

    code, lines = check(tmp_path, Runner(both), capsys)

    assert code == 1
    (finding,) = [line for line in lines if "test_both" in line and "finding" in line]
    assert "runtime" in finding
    assert "claude_code" in finding
    assert "acp" in finding
    assert "telemetry" not in finding


def test_a_marker_the_runner_does_not_register_is_a_finding_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Runner(CLEAN, registered=("local_stack", "runtime_claude_code", "runtime_acp"))

    code, lines = check(tmp_path, run, capsys)

    assert code == 1
    assert any("telemetry_otel" in line and "register" in line for line in lines)


def test_a_marker_declared_by_two_values_is_a_finding_naming_the_marker_and_both_values() -> None:
    dimensions = {
        "runtime": {
            "claude_code": E2eDimensionValue.model_construct(marker="runtime_shared"),
            "acp": E2eDimensionValue.model_construct(marker="runtime_shared"),
        }
    }

    result = check_dimensions(
        PROFILE,
        ["uv", "run", "pytest", "-m", "local_stack"],
        "local_stack",
        dimensions,
        (),
        run=Runner({}),
    )

    (finding,) = [f for f in result.findings if "runtime_shared" in f]
    assert re.search(r"runtime.claude_code", finding)
    assert re.search(r"runtime.acp", finding)
