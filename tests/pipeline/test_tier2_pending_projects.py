"""Tier 2 runs only the active projects and reports a pending one (spec: project-init)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.wiring import Tier2Session
from tests.factories import unit
from tests.tier2_failure_fakes import checkout

PASSED = "3 passed in 4.00s"


def run_e2e(
    tmp_path: Path, root: Path, projects: list[ProjectConfig]
) -> tuple[bool, list[Path], list[str]]:
    where: list[Path] = []
    log: list[str] = []

    def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
        where.append(Path(kwargs["cwd"]))
        return subprocess.CompletedProcess(command, 0, PASSED, "")

    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=run,
        sha=lambda cwd: "abc1234",
        projects=projects,
        log=log.append,
    )
    ok, _ = session.run(cwd=root)
    return ok, where, log


def test_only_the_active_projects_tests_run_and_the_pending_one_is_reported(
    tmp_path: Path,
) -> None:
    root = checkout(tmp_path, "api")

    ok, where, log = run_e2e(tmp_path, root, [ProjectConfig(path="api"), ProjectConfig(path="web")])

    assert ok
    assert where
    assert set(where) == {root / "api"}
    assert [line for line in log if "pending" in line and "web" in line]


def test_a_repo_of_only_pending_projects_runs_nothing_and_passes(tmp_path: Path) -> None:
    root = checkout(tmp_path)

    ok, where, log = run_e2e(tmp_path, root, [ProjectConfig(path="web")])

    assert ok
    assert where == []
    assert [line for line in log if "pending" in line and "web" in line]
