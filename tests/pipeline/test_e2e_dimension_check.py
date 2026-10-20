"""`abk e2e-test check` over dimensions: a test with two values of one dimension and a marker
the runner does not register are findings, a clean repo has none, and a marker declared twice
is named (spec: e2e-dimensions)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from agent_build_kit.cli import e2e_cmd
from agent_build_kit.config import E2eDimensionValue
from agent_build_kit.pipeline.e2e_exclusive import check_dimensions
from agent_build_kit.profiles.python_uv import PROFILE
from tests.e2e_check_support import Pytest, installation, markers_output

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


def runner(tests: dict[str, set[str]], registered: tuple[str, ...] = REGISTERED) -> Pytest:
    return Pytest(carries=tests, markers=markers_output(registered))


def check(
    tmp_path: Path,
    run: Pytest,
    capsys: pytest.CaptureFixture[str],
    profile: str = "python-uv",
) -> tuple[int, list[str]]:
    found = installation(tmp_path, splits=None, dimensions=DIMENSIONS, profile=profile)
    capsys.readouterr()
    code = e2e_cmd.cmd_e2e_check(argparse.Namespace(repo="app"), found, run=run)
    shown = capsys.readouterr()
    return code, (shown.out + shown.err).splitlines()


def test_a_repo_with_each_test_carrying_at_most_one_value_per_dimension_has_no_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = check(tmp_path, runner(CLEAN), capsys)

    assert code == 0
    assert not [line for line in lines if "finding" in line]
    counts = [line.split() for line in lines if "=" in line and line.endswith("tests")]
    assert counts == [
        ["runtime=claude_code", "1", "tests"],
        ["runtime=acp", "2", "tests"],
        ["telemetry=otel", "1", "tests"],
        ["telemetry=local", "0", "tests"],
    ]


def test_a_test_with_two_values_of_one_dimension_is_named_with_the_dimension_and_the_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    both = {**CLEAN, f"{LIVE}test_both": {"local_stack", "runtime_claude_code", "runtime_acp"}}

    code, lines = check(tmp_path, runner(both), capsys)

    assert code == 1
    (finding,) = [line for line in lines if "test_both" in line and "finding" in line]
    assert "runtime" in finding
    assert "claude_code" in finding
    assert "acp" in finding
    assert "telemetry" not in finding


def test_a_marker_the_runner_does_not_register_is_a_finding_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = runner(CLEAN, registered=("local_stack", "runtime_claude_code", "runtime_acp"))

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
        run=runner({}, registered=("local_stack", "runtime_shared")),
    )

    (finding,) = [f for f in result.findings if "runtime_shared" in f]
    assert re.search(r"runtime.claude_code", finding)
    assert re.search(r"runtime.acp", finding)


def test_a_profile_that_cannot_list_by_marker_is_reported_and_not_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = runner(CLEAN)

    code, lines = check(tmp_path, run, capsys, profile="node-npm")

    assert code == 1
    (reason,) = [line for line in lines if "cannot be applied" in line]
    assert "app" in reason
    assert "marker selector" in reason
    assert not run.commands
