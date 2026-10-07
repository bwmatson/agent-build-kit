"""Tier 1 runs the changelog check through the toolchain profile, for a repo that has it on."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.wiring import build_tier1


def repo_config(path: Path, *, changelog: str | None = "CHANGELOG.md") -> RepoConfig:
    return RepoConfig(path=path, slug="example/app", changelog=changelog)


def is_changelog_check(command: list[str]) -> bool:
    words = " ".join(command)
    return "changelog" in words and "check" in words


def checkout(tmp_path: Path) -> Path:
    path = tmp_path / "app"
    (path / "tests").mkdir(parents=True)
    (path / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    return path


def test_the_python_profile_adds_the_changelog_check_when_the_setting_is_on(
    tmp_path: Path,
) -> None:
    commands = profiles.get("python-uv").extra_checks(repo_config(tmp_path))

    assert [c for c in commands if is_changelog_check(c)]


def test_the_python_profile_adds_nothing_when_the_setting_is_off(tmp_path: Path) -> None:
    assert profiles.get("python-uv").extra_checks(repo_config(tmp_path, changelog=None)) == []


def test_tier_one_runs_the_changelog_check_beside_lint_and_tests(tmp_path: Path) -> None:
    app = checkout(tmp_path)
    ran: list[list[str]] = []

    def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        ran.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    passed, _ = build_tier1(run=run, changed=lambda *a: ["tests/test_x.py"], repo=repo_config(app))(
        cwd=app, base="main"
    )

    assert passed
    assert [c for c in ran if is_changelog_check(c)]
    assert [c for c in ran if "pre-commit" in c]


def test_tier_one_runs_no_changelog_check_when_the_setting_is_off(tmp_path: Path) -> None:
    app = checkout(tmp_path)
    ran: list[list[str]] = []

    def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        ran.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    build_tier1(
        run=run, changed=lambda *a: ["tests/test_x.py"], repo=repo_config(app, changelog=None)
    )(cwd=app, base="main")

    assert ran
    assert not [c for c in ran if is_changelog_check(c)]


def test_tier_one_fails_the_checks_round_on_a_changelog_problem(tmp_path: Path) -> None:
    app = checkout(tmp_path)
    problem = "CHANGELOG.md line 9: bullet not separated by a blank line"

    def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        if is_changelog_check(command):
            return subprocess.CompletedProcess(command, 1, f"{problem}\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    passed, output = build_tier1(
        run=run, changed=lambda *a: ["tests/test_x.py"], repo=repo_config(app)
    )(cwd=app, base="main")

    assert not passed
    assert problem in output


def run_emitted_check(app: Path) -> subprocess.CompletedProcess:
    """The command the profile emits for the repo, run as tier 1 runs it: in the checkout."""
    command = profiles.get("python-uv").extra_checks(repo_config(app))[0]
    return subprocess.run(command, cwd=app, capture_output=True, text=True, check=False)


def test_the_emitted_check_fails_a_changelog_with_bullets_run_together(tmp_path: Path) -> None:
    app = checkout(tmp_path)
    (app / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n- First change.\n- Second change.\n"
    )

    result = run_emitted_check(app)

    assert result.returncode == 1
    assert "CHANGELOG.md line 6" in result.stdout


def test_the_emitted_check_passes_a_well_formed_changelog(tmp_path: Path) -> None:
    app = checkout(tmp_path)
    (app / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n- First change.\n\n- Second change.\n"
    )

    result = run_emitted_check(app)

    assert result.returncode == 0, result.stdout + result.stderr
