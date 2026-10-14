"""The validator `abk init` and the propose track use refuses a heading naming a project the
repo does not declare, with the declared ones listed (spec: unit-projects)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.init.propose import validation_errors
from tests.factories import init_repo
from tests.init.test_propose import valid_report, write_change

CHANGE = "app-feature"
PROJECTS = {"platform": (), "app": ("web",)}


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = init_repo(tmp_path / "planning")
    (root / "openspec" / "changes").mkdir(parents=True)
    return root


def errors_for(planning: Path, heading: str) -> list[str]:
    write_change(planning, CHANGE, f"## 1. {heading}\n\n- [ ] 1.1 A task\n")
    return validation_errors(
        planning,
        CHANGE,
        repos=("platform", "app"),
        projects=PROJECTS,
        run_openspec=valid_report(planning),
    )


def test_an_undeclared_project_is_an_error_naming_it_and_the_declared_ones(planning: Path) -> None:
    (error,) = [e for e in errors_for(planning, "[app/mobile] [tier1] Add it") if "mobile" in e]

    assert "web" in error


def test_a_declared_project_is_no_error(planning: Path) -> None:
    assert not [e for e in errors_for(planning, "[app/web] [tier1] Add it") if "project" in e]
