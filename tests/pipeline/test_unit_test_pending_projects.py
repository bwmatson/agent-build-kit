"""Unit-test skips a project whose directory is absent from the checkout and says so
(spec: project-init).

The runner is the faked boundary, as in the affected-tests tests: it records each argv and
the directory it ran in.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.wiring import build_unit_test
from tests.pipeline.test_unit_test_affected import Commands, Profile


def unit_test(
    checkout: Path, changed: list[str], projects: list[ProjectConfig]
) -> tuple[bool, list[Path], list[str]]:
    commands = Commands()
    log: list[str] = []
    ok, _ = build_unit_test(
        run=commands,
        changed=lambda *a: changed,
        profile=Profile(),
        projects=projects,
        log=log.append,
    )(cwd=checkout, base="main")
    return ok, commands.directories, log


def pending_lines(log: list[str], path: str) -> list[str]:
    return [line for line in log if "pending" in line and path in line]


def test_a_missing_project_runs_nothing_and_is_named_with_its_path(tmp_path: Path) -> None:
    (tmp_path / "api").mkdir()

    ok, directories, log = unit_test(
        tmp_path, ["api/x.py"], [ProjectConfig(path="api"), ProjectConfig(path="web")]
    )

    assert ok
    assert directories
    assert set(directories) == {tmp_path / "api"}
    assert len(pending_lines(log, "web")) == 1


def test_a_diff_touching_no_file_of_a_missing_project_still_runs_nothing_in_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "api").mkdir()

    ok, directories, log = unit_test(
        tmp_path, ["README.md"], [ProjectConfig(path="api"), ProjectConfig(path="web")]
    )

    assert ok
    assert tmp_path / "web" not in directories
    assert pending_lines(log, "web")


def test_the_project_the_unit_creates_is_not_pending_and_is_checked_in_it(
    tmp_path: Path,
) -> None:
    (tmp_path / "web").mkdir()

    ok, directories, log = unit_test(
        tmp_path, ["web/a.py"], [ProjectConfig(path="api"), ProjectConfig(path="web")]
    )

    assert ok
    assert directories
    assert set(directories) == {tmp_path / "web"}
    assert not pending_lines(log, "web")
    assert pending_lines(log, "api")


def test_a_unit_that_produced_nothing_does_not_pass_on_pending_projects(tmp_path: Path) -> None:
    commands = Commands()

    ok, output = build_unit_test(
        run=commands,
        changed=lambda *a: [],
        profile=Profile(),
        projects=[ProjectConfig(path="web")],
    )(cwd=tmp_path, base="main", whole_repo=True)

    assert not ok
    assert "web" in output
    assert "produced nothing" in output
    assert commands.directories == []


def test_a_repo_of_only_pending_projects_runs_nothing_passes_and_says_so(tmp_path: Path) -> None:
    ok, directories, log = unit_test(
        tmp_path, ["docs/a.md"], [ProjectConfig(path="api"), ProjectConfig(path="web")]
    )

    assert ok
    assert directories == []
    assert pending_lines(log, "api") and pending_lines(log, "web")
    assert any("nothing ran" in line for line in log)


tier1 = unit_test  # abk-shim
