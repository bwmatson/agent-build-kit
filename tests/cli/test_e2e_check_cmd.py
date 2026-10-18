"""`abk e2e-test check`: one line per split and `rest` with its marker and test count, the findings,
the exit codes, and nothing changed on disk (spec: e2e-splits)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import e2e_cmd
from agent_build_kit.installation import Installation
from tests.cli.policy_static_cli import snapshot
from tests.e2e_check_support import ACP, BASE, CLAUDE, CLEAN, Pytest, installation


def check(
    found: Installation, run: Pytest, capsys: pytest.CaptureFixture[str], repo: str | None = "app"
) -> tuple[int, list[str]]:
    capsys.readouterr()
    code = e2e_cmd.cmd_e2e_check(argparse.Namespace(repo=repo), found, run=run)
    shown = capsys.readouterr()
    return code, (shown.out + shown.err).splitlines()


def test_exclusive_splits_print_one_line_each_with_marker_and_count_and_exit_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, lines = check(installation(tmp_path), Pytest(CLEAN), capsys)

    assert code == 0
    (acp,) = [line for line in lines if "acp" in line and "claude_code" not in line]
    assert "runtime_acp" in acp and acp.endswith(" 1 tests")
    assert any(
        "claude_code" in line and "runtime_claude_code" in line and line.endswith(" 1 tests")
        for line in lines
    )
    assert any(line.lstrip().startswith("rest") and line.endswith(" 1 tests") for line in lines)


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


def test_every_listing_runs_in_the_checkout_under_the_verify_env(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Pytest(CLEAN)

    check(installation(tmp_path), run, capsys)

    assert run.kwargs
    assert all(call["cwd"] == tmp_path / "app" for call in run.kwargs)
    assert all(call["env"]["SVC_TOKEN"] == "secret" for call in run.kwargs)
    assert all(call["capture_output"] is True and call["text"] is True for call in run.kwargs)


def test_each_declared_project_is_listed_from_its_own_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    projects = [
        {"path": "svc-a", "profile": "python-uv"},
        {"path": "svc-b", "profile": "python-uv"},
    ]
    run = Pytest(CLEAN)

    code, _ = check(installation(tmp_path, projects=projects), run, capsys)

    assert code == 0
    assert {call["cwd"] for call in run.kwargs} == {
        tmp_path / "app" / "svc-a",
        tmp_path / "app" / "svc-b",
    }


def test_a_node_project_that_cannot_apply_a_marker_selector_is_reported_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    projects = [
        {"path": "svc-a", "profile": "python-uv"},
        {"path": "web", "profile": "node-npm"},
    ]

    code, lines = check(installation(tmp_path, projects=projects), Pytest(CLEAN), capsys)

    assert code == 1
    assert any("node-npm" in line and "marker" in line and "web" in line for line in lines)


def test_without_a_name_every_repo_is_checked_and_the_exit_code_is_the_worst(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    overlapping = Pytest({**CLEAN, f"{BASE} and runtime_claude_code": [CLAUDE, ACP]})
    clean = Pytest(CLEAN)

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        return (overlapping if kwargs["cwd"] == tmp_path / "platform" else clean)(argv, **kwargs)

    capsys.readouterr()
    code = e2e_cmd.cmd_e2e_check(argparse.Namespace(repo=None), installation(tmp_path), run=run)
    lines = capsys.readouterr().out.splitlines()

    assert code == 1
    assert "app:" in lines and "platform:" in lines
