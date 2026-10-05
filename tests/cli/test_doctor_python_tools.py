"""`abk doctor`: a Python tool's version has one owner, the lock."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import skills
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from agent_build_kit.init.scaffold import render_openspec_config
from tests.factories import init_repo

HOOKS_FILE = ".pre-commit-config.yaml"


def ok_run(argv, **kwargs):
    if argv[0] == "git":
        return subprocess.run(argv, **kwargs)
    if argv[0] == "npx":
        return subprocess.CompletedProcess(argv, 0, "1.0.0\n", "")
    if argv[0] == "gh":
        return subprocess.CompletedProcess(argv, 0, "tok\n", "")
    return subprocess.CompletedProcess(argv, 0, "", "")


def which_all(name: str) -> str | None:
    return f"/usr/bin/{name}"


def pyproject(*dev: str) -> str:
    deps = ", ".join(f'"{d}"' for d in dev)
    return f'[project]\nname = "app"\nversion = "0"\n\n[dependency-groups]\ndev = [{deps}]\n'


PINNED_HOOK = """\
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.8
    hooks:
      - id: ruff-format
      - id: ruff
  - repo: https://github.com/facebook/pyrefly-pre-commit
    rev: 1.3.1
    hooks:
      - id: pyrefly-check
"""

YAMLLINT_HOOK = """\
repos:
  - repo: https://github.com/adrienverge/yamllint
    rev: v1.38.0
    hooks:
      - id: yamllint
"""


def local_hook(tool: str, entry: str | None = None) -> str:
    return f"""\
repos:
  - repo: local
    hooks:
      - id: {tool}
        name: {tool}
        entry: {entry or f"uv run --frozen {tool} check"}
        language: system
        types: [python]
"""


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    root = init_repo(tmp_path / "planning")
    app = init_repo(tmp_path / "app")
    config = WorkspaceConfig(repos={"app": RepoConfig(path=app, slug="example/app")})
    (root / "abk.yaml").write_text(dump(config))
    (root / "openspec").mkdir()
    (root / "openspec" / "config.yaml").write_text(render_openspec_config(config))
    skills.install(root / ".claude" / "skills")
    return root


def doctor(planning: Path, tmp_path: Path, *, pyproject_text: str, hooks: str) -> list[Check]:
    (tmp_path / "app" / "pyproject.toml").write_text(pyproject_text)
    (tmp_path / "app" / HOOKS_FILE).write_text(hooks)
    return run_doctor(planning / "abk.yaml", run=ok_run, which=which_all)


def warnings(checks: list[Check], tool: str) -> list[Check]:
    return [
        c for c in checks if c.status == "warn" and tool in f"{c.name} {c.detail} {c.fix}".lower()
    ]


def test_a_tool_pinned_in_the_group_and_by_a_hook_rev_warns_once_naming_both_files(
    planning: Path, tmp_path: Path
) -> None:
    checks = doctor(
        planning,
        tmp_path,
        pyproject_text=pyproject("ruff==0.16.8", "pyrefly==1.3.1"),
        hooks=PINNED_HOOK,
    )

    for tool in ("ruff", "pyrefly"):
        found = warnings(checks, tool)
        assert len(found) == 1, (tool, found)
        text = f"{found[0].detail} {found[0].fix}"
        assert "pyproject.toml" in text and HOOKS_FILE in text


def test_only_the_tool_pinned_twice_is_named(planning: Path, tmp_path: Path) -> None:
    checks = doctor(planning, tmp_path, pyproject_text=pyproject("ruff==0.16.8"), hooks=PINNED_HOOK)

    assert len(warnings(checks, "ruff")) == 1
    assert warnings(checks, "pyrefly") == []


def test_a_tool_pinned_in_one_place_only_is_silent(planning: Path, tmp_path: Path) -> None:
    hook_only = doctor(planning, tmp_path, pyproject_text=pyproject(), hooks=PINNED_HOOK)
    group_only = doctor(
        planning, tmp_path, pyproject_text=pyproject("ruff==0.16.8"), hooks=YAMLLINT_HOOK
    )
    local = doctor(
        planning, tmp_path, pyproject_text=pyproject("ruff==0.16.8"), hooks=local_hook("ruff")
    )

    for checks in (hook_only, group_only, local):
        assert [c for c in checks if c.status == "warn"] == []


def test_a_system_hook_for_a_tool_outside_the_group_warns(planning: Path, tmp_path: Path) -> None:
    checks = doctor(
        planning, tmp_path, pyproject_text=pyproject("pytest>=8"), hooks=local_hook("ruff")
    )

    found = warnings(checks, "ruff")
    assert len(found) == 1
    assert HOOKS_FILE in f"{found[0].detail} {found[0].fix}"


def test_a_system_hook_for_a_tool_in_the_group_is_silent(planning: Path, tmp_path: Path) -> None:
    checks = doctor(
        planning,
        tmp_path,
        pyproject_text=pyproject("ruff==0.16.8"),
        hooks=local_hook("ruff", "uv run --frozen ruff format"),
    )

    assert [c for c in checks if c.status == "warn"] == []


HYGIENE_HOOK = """\
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: trailing-whitespace
      - id: check-toml
"""


def test_a_hygiene_hook_repo_is_not_a_second_pin_of_pre_commit(
    planning: Path, tmp_path: Path
) -> None:
    checks = doctor(
        planning, tmp_path, pyproject_text=pyproject("pre-commit>=4"), hooks=HYGIENE_HOOK
    )

    assert warnings(checks, "pre-commit") == []


def test_a_uv_run_flag_with_a_value_is_not_read_as_the_tool(planning: Path, tmp_path: Path) -> None:
    checks = doctor(
        planning,
        tmp_path,
        pyproject_text=pyproject("ruff==0.16.8"),
        hooks=local_hook("ruff", "uv run --frozen --project sub ruff check"),
    )

    assert [c for c in checks if c.status == "warn"] == []


def test_a_uv_run_of_python_the_project_s_scripts_or_its_dependencies_is_silent(
    planning: Path, tmp_path: Path
) -> None:
    scripted = pyproject("ruff==0.16.8") + '\n[project.scripts]\napp-cli = "app:main"\n'
    runtime_dep = (
        '[project]\nname = "app"\nversion = "0"\ndependencies = ["Black>=24"]\n'
        '[project.optional-dependencies]\nfmt = ["isort"]\n'
    )
    cases = [
        (pyproject("ruff==0.16.8"), "uv run --frozen python -m pytest"),
        (scripted, "uv run app-cli"),
        (runtime_dep, "uv run black ."),
        (runtime_dep, "uv run isort ."),
        (pyproject("ruff==0.16.8"), "uv run --no-group lint ruff check"),
    ]

    for text, entry in cases:
        checks = doctor(planning, tmp_path, pyproject_text=text, hooks=local_hook("tool", entry))
        assert [c for c in checks if c.status == "warn"] == [], entry


def test_a_hook_list_or_group_that_is_not_a_list_does_not_stop_doctor(
    planning: Path, tmp_path: Path
) -> None:
    checks = doctor(
        planning,
        tmp_path,
        pyproject_text='[project]\nname = "app"\nversion = "0"\n\n[dependency-groups]\ndev = "x"\n',
        hooks="repos:\n  - repo: local\n    hooks:\n",
    )

    assert [c for c in checks if c.status == "warn"] == []
