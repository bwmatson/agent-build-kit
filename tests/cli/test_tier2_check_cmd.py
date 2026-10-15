"""`abk tier2 check`: one line per split and `rest` with its marker and test count, the findings,
the exit codes, and nothing changed on disk (spec: tier2-splits)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import tier2_cmd
from agent_build_kit.installation import Installation
from tests.cli.policy_static_cli import snapshot
from tests.conftest import make_installation

SPLITS = {"acp": {"marker": "runtime_acp"}, "claude_code": {"marker": "runtime_claude_code"}}
ACP = "tests/integration/test_live.py::test_acp"
CLAUDE = "tests/integration/test_live.py::test_claude"
PLAIN = "tests/integration/test_live.py::test_plain"
BASE = "local_stack"
MARKERS = (
    "@pytest.mark.local_stack: live stack\n\n"
    "@pytest.mark.runtime_acp: acp\n\n"
    "@pytest.mark.runtime_claude_code: claude code\n"
)


class Pytest:
    """Stands in for the process run: answers `--markers` and each `--collect-only` by the
    `-m` expression it was given."""

    def __init__(
        self,
        listings: dict[str, list[str]] | None = None,
        *,
        markers: str = MARKERS,
        failing: str | None = None,
    ) -> None:
        self.listings = listings or {}
        self.markers = markers
        self.failing = failing
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.commands.append(argv)
        assert "--collect-only" in argv or "--markers" in argv, f"ran a test: {argv}"
        if "--markers" in argv:
            return subprocess.CompletedProcess(argv, 0, self.markers, "")
        expression = argv[argv.index("-m") + 1]
        if expression == self.failing:
            return subprocess.CompletedProcess(argv, 4, "ERROR: usage\n", "")
        tests = self.listings.get(expression, [])
        return subprocess.CompletedProcess(argv, 0 if tests else 5, "\n".join(tests) + "\n", "")


def installation(
    tmp_path: Path, splits: dict[str, Any] | None = SPLITS, profile: str = "python-uv"
) -> Installation:
    root = tmp_path / "planning"
    found = make_installation(
        root,
        tests={} if splits is None else {"tier2_splits": splits},
        repos={
            "app": {
                "path": str(tmp_path / "app"),
                "slug": "example/app",
                "profile": profile,
            },
            "platform": {"path": str(tmp_path / "platform"), "slug": "example/platform"},
        },
    )
    for name in ("app", "platform"):
        (tmp_path / name / "tests" / "integration").mkdir(parents=True)
        (tmp_path / name / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
        (tmp_path / name / "tests" / "integration" / "test_live.py").write_text("")
    return found


def check(
    found: Installation, run: Pytest, capsys: pytest.CaptureFixture[str], repo: str = "app"
) -> tuple[int, list[str]]:
    capsys.readouterr()
    code = tier2_cmd.cmd_tier2_check(argparse.Namespace(repo=repo), found, run=run)
    shown = capsys.readouterr()
    return code, (shown.out + shown.err).splitlines()


CLEAN = {
    f"{BASE} and runtime_acp": [ACP],
    f"{BASE} and runtime_claude_code": [CLAUDE],
    f"{BASE} and not runtime_acp and not runtime_claude_code": [PLAIN],
}


def test_exclusive_splits_print_one_line_each_with_marker_and_count_and_exit_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = check(installation(tmp_path), Pytest(CLEAN), capsys)

    assert code == 0
    (acp,) = [line for line in lines if "acp" in line and "claude_code" not in line]
    assert "runtime_acp" in acp and "1" in acp
    assert any("claude_code" in line and "runtime_claude_code" in line for line in lines)
    assert any(line.lstrip().startswith("rest") and "1" in line for line in lines)


def test_a_test_in_two_splits_is_printed_with_both_names_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listings = {**CLEAN, f"{BASE} and runtime_claude_code": [CLAUDE, ACP]}

    code, lines = check(installation(tmp_path), Pytest(listings), capsys)

    assert code == 1
    (finding,) = [line for line in lines if ACP in line and "claude_code" in line]
    assert "acp" in finding


def test_an_unknown_selector_is_printed_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    markers = "@pytest.mark.local_stack: live stack\n\n@pytest.mark.runtime_acp: acp\n"

    code, lines = check(installation(tmp_path), Pytest(CLEAN, markers=markers), capsys)

    assert code == 1
    assert any("runtime_claude_code" in line and "unknown" in line.lower() for line in lines)


def test_a_failed_listing_is_printed_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Pytest(CLEAN, failing=f"{BASE} and runtime_acp")

    code, lines = check(installation(tmp_path), run, capsys)

    assert code == 1
    assert any("acp" in line and "fail" in line.lower() for line in lines)


def test_a_split_the_profile_cannot_apply_names_the_profile_and_the_kind_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = check(installation(tmp_path, profile="node-npm"), Pytest(), capsys)

    assert code == 1
    assert any("node-npm" in line and "marker" in line for line in lines)


def test_a_repo_with_no_declared_split_says_so_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Pytest()

    code, lines = check(installation(tmp_path, splits=None), run, capsys)

    assert code == 0
    assert any("no split" in line.lower() for line in lines)
    assert run.commands == []


def test_a_repo_it_does_not_know_exits_two_naming_the_repos_there_are(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = check(installation(tmp_path), Pytest(), capsys, repo="nope")

    assert code == 2
    text = "\n".join(lines)
    assert "nope" in text and "app" in text and "platform" in text


def test_it_changes_nothing_on_disk_and_runs_no_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    found = installation(tmp_path)
    before = snapshot(tmp_path)
    run = Pytest(CLEAN)

    check(found, run, capsys)

    assert snapshot(tmp_path) == before
    assert run.commands
