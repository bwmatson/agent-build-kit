"""Wiring runs each pre-commit command with the configuration found for the folder it runs in
(spec: shared-quality-gate).

A repo whose one configuration sits at its root and whose projects sit below it. The command
runner is the boundary and records every argv with the folder it ran in; git runs for real
where the code reads the tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.pipeline.wiring import build_fixers, build_stub_checks, build_unit_test
from tests.conftest import make_installation
from tests.factories import commit_files, init_repo
from tests.fixers_fakes import FakeRun, activate_app

CONFIG = ".pre-commit-config.yaml"
ONE = ProjectConfig(path="one")
TWO = ProjectConfig(path="two")


def repo_with_root_config(tmp_path: Path) -> Path:
    """A git repo with one pre-commit configuration, at its root, and a file in each project."""
    repo = init_repo(tmp_path / "app")
    commit_files(
        repo, "start", {CONFIG: "repos: []\n", "one/a.py": "x = 1\n", "two/b.py": "y = 1\n"}
    )
    return repo


def config_args(calls: list[tuple[list[str], Path]], flag: str = "") -> list[tuple[Path, str]]:
    """For each recorded pre-commit command holding `flag`, the folder it ran in and what
    `--config` named (empty when it names none)."""
    found = []
    for argv, where in calls:
        words = argv[-1].split() if argv[:2] == ["sh", "-c"] else argv
        if "pre-commit" in words and flag in words:
            found.append((where, words[words.index("--config") + 1] if "--config" in words else ""))
    return found


def test_the_stub_checks_of_each_project_and_of_the_root_use_the_root_configuration(
    tmp_path: Path,
) -> None:
    repo = repo_with_root_config(tmp_path)
    (repo / "one" / "new.py").write_text("z = 1\n")
    (repo / "two" / "new.py").write_text("z = 1\n")
    (repo / "uv.lock").write_text("lock\n")
    run = FakeRun()

    ok, output = build_stub_checks(profile=profiles.get("python-uv"), projects=[ONE, TWO], run=run)(
        cwd=repo
    )

    assert ok, output
    assert sorted(config_args(run.calls)) == [
        (repo, CONFIG),
        (repo / "one", f"../{CONFIG}"),
        (repo / "two", f"../{CONFIG}"),
    ]


def test_the_fixer_of_each_project_uses_the_root_configuration(tmp_path: Path) -> None:
    activate_app()
    repo = repo_with_root_config(tmp_path)
    (repo / "one" / "a.py").write_text("x=2\n")
    (repo / "two" / "b.py").write_text("y=2\n")
    run = FakeRun()

    build_fixers(profile=profiles.get("python-uv"), projects=[ONE, TWO], repo_name="app", run=run)(
        cwd=repo
    )

    assert run.calls, "the fixers ran"
    assert {where for _, where in run.calls} == {repo / "one", repo / "two"}
    assert set(config_args(run.calls)) == {
        (repo / "one", f"../{CONFIG}"),
        (repo / "two", f"../{CONFIG}"),
    }


def test_the_lint_of_each_project_and_of_the_root_uses_the_root_configuration(
    tmp_path: Path,
) -> None:
    repo = repo_with_root_config(tmp_path)
    app = RepoConfig(path=repo, slug="example/app", changelog=None, projects=[ONE, TWO])
    make_installation(tmp_path / "meta", repos={"app": app.model_dump(mode="json")})
    ran: list[tuple[list[str], Path]] = []

    def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        ran.append((list(command), cwd))
        return subprocess.CompletedProcess(command, 0, "", "")

    ok, output = build_unit_test(
        run=run,
        changed=lambda *a: ["one/a.py", "two/b.py", "uv.lock"],
        profile=profiles.get("python-uv"),
        repo=app,
        projects=[ONE, TWO],
    )(cwd=repo, base="main")

    assert ok, output
    lints = config_args(ran, "--from-ref")
    assert {where for where, _ in lints} >= {repo / "one", repo / "two"}
    assert all(
        config == (CONFIG if where == repo else f"../{CONFIG}") for where, config in lints
    ), lints
