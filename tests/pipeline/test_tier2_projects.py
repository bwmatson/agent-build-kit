"""Tier 2 runs in each of a repo's declared projects, as tier 1 does.

The runner is injected at the process boundary: it records what would have
been started and where, and answers with what pytest prints.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.wiring import Tier2Session
from agent_build_kit.profiles import node_npm
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON_UV
from tests.factories import unit

PASSED = "3 passed in 4.00s"
FAILED = "FAILED tests/test_live.py::test_live - assert 0\n1 failed in 1.00s"
NOTHING = "12 deselected in 0.10s"

Call = tuple[list[str], Path]


def _session(
    tmp_path: Path,
    projects: list[ProjectConfig] | None,
    answers: dict[str, tuple[int, str]],
    calls: list[Call],
) -> Tier2Session:
    """`answers` maps a project's directory name (or `.`) to its (exit, output)."""

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        cwd = Path(kwargs["cwd"])
        calls.append((command, cwd))
        code, out = answers.get(cwd.name if cwd.parent != tmp_path else ".", (0, PASSED))
        return subprocess.CompletedProcess(command, code, out, "")

    return Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=run,
        sha=lambda cwd: "abc1234",
        projects=projects,
    )


def _checkout(tmp_path: Path, *names: str) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    for name in names:
        (root / name).mkdir()
    return root


def test_a_project_in_a_subdirectory_runs_from_it(tmp_path: Path) -> None:
    root = _checkout(tmp_path, "api")
    calls: list[Call] = []
    session = _session(tmp_path, [ProjectConfig(path="api")], {}, calls)

    ok, _ = session.run(cwd=root)

    assert ok
    assert calls
    assert {cwd for _, cwd in calls} == {root / "api"}
    assert calls[0][0] == PYTHON_UV.tier2_commands(root / "api", marker="local_stack")[0]


def test_each_project_uses_its_own_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _checkout(tmp_path, "api", "web")
    monkeypatch.setattr(
        node_npm.PROFILE, "tier2_commands", lambda repo, *, marker: [["npm", "run", marker]]
    )
    monkeypatch.setattr(node_npm.PROFILE, "parse_test_summary", PYTHON_UV.parse_test_summary)
    calls: list[Call] = []
    session = _session(
        tmp_path,
        [ProjectConfig(path="api"), ProjectConfig(path="web", profile="node-npm")],
        {},
        calls,
    )

    ok, _ = session.run(cwd=root)

    assert ok
    assert calls == [
        (["uv", "run", "pytest", "-m", "local_stack", "-v"], root / "api"),
        (["npm", "run", "local_stack"], root / "web"),
    ]


def test_no_projects_runs_once_from_the_root(tmp_path: Path) -> None:
    root = _checkout(tmp_path, "api")
    calls: list[Call] = []
    session = _session(tmp_path, None, {}, calls)

    session.run(cwd=root)

    assert calls == [(["uv", "run", "pytest", "-m", "local_stack", "-v"], root)]


def test_projects_run_in_the_order_declared(tmp_path: Path) -> None:
    root = _checkout(tmp_path, "b", "a")
    calls: list[Call] = []
    session = _session(tmp_path, [ProjectConfig(path="b"), ProjectConfig(path="a")], {}, calls)

    session.run(cwd=root)

    assert [cwd for _, cwd in calls] == [root / "b", root / "a"]


def test_results_are_summed_and_a_failure_names_its_project(tmp_path: Path) -> None:
    root = _checkout(tmp_path, "api", "web")
    calls: list[Call] = []
    session = _session(
        tmp_path,
        [ProjectConfig(path="api"), ProjectConfig(path="web")],
        {"api": (0, PASSED), "web": (1, FAILED)},
        calls,
    )

    ok, snapshot = session.run(cwd=root)

    assert ok is False
    assert session.result is not None
    assert (session.result.passed, session.result.failed) == (3, 1)
    failing = session.result.output.split("$ ")[-1]
    assert "web" in failing
    assert "assert 0" in failing
    assert "web" in snapshot


def test_a_project_where_nothing_is_selected_is_a_pass(tmp_path: Path) -> None:
    root = _checkout(tmp_path, "api", "web")
    calls: list[Call] = []
    session = _session(
        tmp_path,
        [ProjectConfig(path="api"), ProjectConfig(path="web")],
        {"api": (0, PASSED), "web": (5, NOTHING)},
        calls,
    )

    ok, _ = session.run(cwd=root)

    assert ok
    assert len(calls) == 2
    assert session.result is not None
    assert (session.result.passed, session.result.failed) == (3, 0)


def test_the_dev_stack_script_still_runs_from_the_root(tmp_path: Path) -> None:
    root = _checkout(tmp_path, "api", "scripts")
    (root / "scripts" / "dev-stack.sh").write_text("#!/bin/sh\n")
    calls: list[Call] = []
    session = _session(tmp_path, [ProjectConfig(path="api")], {}, calls)

    ok, _ = session.run(cwd=root)

    assert ok
    assert calls
    assert {cwd for _, cwd in calls} == {root}
    assert {command[0] for command, _ in calls} == {"scripts/dev-stack.sh"}


def test_real_pytest_in_a_project_collects_only_its_testpaths(tmp_path: Path) -> None:
    """Real pytest, the runner swapping only `uv run` for this interpreter: the
    project's `testpaths` decide collection, so decoys outside it — beside the
    project's tests and at the checkout root — are never imported."""
    root = tmp_path / "checkout"
    project = root / "api"
    (project / "tests").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "api"\n\n[tool.pytest.ini_options]\n'
        'testpaths = ["tests"]\nmarkers = ["local_stack: needs the live stack"]\n'
    )
    (project / "tests" / "test_live.py").write_text(
        "import pytest\n\n\n@pytest.mark.local_stack\ndef test_live() -> None:\n    pass\n"
    )
    decoy = 'raise SystemExit("optional package missing")\n'
    (project / "smoke_test.py").write_text(decoy)
    (root / "root_smoke_test.py").write_text(decoy)

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        assert command[:3] == ["uv", "run", "pytest"]
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *command[3:]],
            cwd=kwargs["cwd"],
            capture_output=True,
            text=True,
            check=False,
        )

    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        run=run,
        sha=lambda cwd: "abc1234",
        projects=[ProjectConfig(path="api")],
    )

    ok, snapshot = session.run(cwd=root)

    assert ok, snapshot
    assert session.result is not None
    assert session.result.passed == 1
    assert "smoke_test" not in snapshot
