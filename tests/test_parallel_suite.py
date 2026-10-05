"""The whole-suite command runs in parallel workers; a single file does not,
and a test that cannot share a process runs in its own serial pass."""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def pytest_options() -> dict:
    return pyproject()["tool"]["pytest"]["ini_options"]


def command_lines(name: str) -> list[str]:
    """The command lines a poe task runs, following sequence steps and task references."""
    tasks = pyproject()["tool"]["poe"]["tasks"]

    def lines(task: object) -> list[str]:
        if isinstance(task, str):
            return [task]
        assert isinstance(task, dict), task
        if "cmd" in task:
            return [task["cmd"]]
        if "shell" in task:
            return [task["shell"]]
        if "ref" in task:
            return [task["ref"]]
        out: list[str] = []
        for step in task.get("sequence", []):
            if isinstance(step, str) and step in tasks:
                out += lines(tasks[step])
            else:
                out += lines(step)
        return out

    return lines(tasks[name])


def pytest_invocations(name: str) -> list[list[str]]:
    return [shlex.split(line) for line in command_lines(name) if re.search(r"\bpytest\b", line)]


def has_workers_flag(argv: list[str]) -> bool:
    return any(re.fullmatch(r"-n(\d+|auto|logical)?|--numprocesses(=.*)?", arg) for arg in argv)


def marker_expression(argv: list[str]) -> str:
    for i, arg in enumerate(argv):
        if arg == "-m":
            return argv[i + 1]
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:]
    return ""


def test_xdist_is_a_dev_dependency() -> None:
    dev = pyproject()["dependency-groups"]["dev"]

    assert any(re.match(r"pytest-xdist\b", dep) for dep in dev)


def test_the_whole_suite_command_distributes_across_workers() -> None:
    invocations = pytest_invocations("test")

    assert any(has_workers_flag(argv) for argv in invocations)


def test_the_workers_are_capped() -> None:
    parallel = [argv for argv in pytest_invocations("test") if has_workers_flag(argv)]

    assert parallel
    for argv in parallel:
        assert any(arg.startswith("--maxprocesses") for arg in argv), argv


def test_addopts_leaves_a_single_file_single_process() -> None:
    addopts = shlex.split(pytest_options()["addopts"])

    assert not has_workers_flag(addopts)
    assert not any(arg.startswith("--maxprocesses") for arg in addopts)


def test_ci_runs_the_suite_with_the_poe_command() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    jobs = yaml.safe_load(ci)["jobs"]
    runs = [step["run"] for step in jobs["test"]["steps"] if "run" in step]

    assert any(re.search(r"\bpoe test\s*$", run.strip()) for run in runs), runs


def test_the_serial_marker_is_registered() -> None:
    markers = pytest_options()["markers"]

    assert any(marker.startswith("serial:") for marker in markers)


def test_the_parallel_pass_excludes_serial_tests() -> None:
    parallel = [argv for argv in pytest_invocations("test") if has_workers_flag(argv)]

    assert parallel
    for argv in parallel:
        assert "not serial" in marker_expression(argv), argv


def test_a_serial_pass_runs_the_serial_tests_without_workers() -> None:
    serial = [
        argv
        for argv in pytest_invocations("test")
        if not has_workers_flag(argv)
        and re.search(r"\bserial\b", marker_expression(argv))
        and "not serial" not in marker_expression(argv)
    ]

    assert serial


def test_the_serial_pass_keeps_the_default_tier_exclusions() -> None:
    serial = [
        argv
        for argv in pytest_invocations("test")
        if not has_workers_flag(argv)
        and re.search(r"\bserial\b", marker_expression(argv))
        and "not serial" not in marker_expression(argv)
    ]

    assert serial
    for argv in serial:
        expression = marker_expression(argv)
        assert "not integration" in expression, argv
        assert "not local_stack" in expression, argv
