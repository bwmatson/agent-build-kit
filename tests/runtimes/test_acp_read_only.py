"""A run whose `allowed_tools` names no edit tool — the reviewer's — is held
read-only by the permission broker: every edit approval is refused, and a
command is allowed only when one of the list's `Bash(...)` patterns covers it.
A build-mode run is unaffected."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.runtimes import AgentRequest, ToolPolicy
from agent_build_kit.runtimes.acp import AcpRuntime
from tests.factories import git, init_repo
from tests.runtimes.acp_agent import requests, use_agent

REVIEW_TOOLS = "Read Grep Glob Bash(git diff*) Bash(git log*) Bash(git show*)"
REFUSING = ("reject_once", "reject_always")


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    path = init_repo(tmp_path / "worktree")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("MARKER = None\n")
    git(path, "checkout", "-q", "-b", "spec/add-marker/1")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "start")
    return path


@pytest.fixture
def specs(tmp_path: Path) -> Path:
    path = tmp_path / "planning" / "openspec" / "specs"
    path.mkdir(parents=True)
    return path


def _review(
    record: Path, worktree: Path, specs: Path, lines: list[str] | None = None, **agent: Any
):
    use_agent(record, **agent)
    return AcpRuntime().run(
        AgentRequest(
            prompt="Review the branch.",
            role="review",
            cwd=worktree,
            add_dirs=(specs,),
            allowed_tools=REVIEW_TOOLS,
            permission_mode="edit",
            policy=ToolPolicy(specs_dir=specs),
            on_event=lines.append if lines is not None else None,
        )
    )


def _asked(record: Path) -> list[dict[str, Any]]:
    return requests(record, "did/ask")


def test_an_edit_request_is_refused_in_a_read_only_run(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    inside = str(worktree / "src" / "app.py")

    result = _review(record, worktree, specs, act=[{"ask": "edit", "paths": [inside]}])

    [answer] = _asked(record)
    assert answer["optionKind"] in REFUSING, answer
    assert requests(record, "did/run") == []
    assert result.ok is True


def test_a_command_the_list_covers_is_allowed_and_one_it_does_not_is_refused(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    _review(
        record,
        worktree,
        specs,
        act=[
            {"ask": "execute", "command": "git diff main...HEAD"},
            {"ask": "execute", "command": "git commit -m sneaky"},
            {"ask": "execute", "command": "git diff && git commit -m sneaky"},
        ],
    )

    kinds = [answer["optionKind"] for answer in _asked(record)]
    assert kinds[0] == "allow_once", kinds
    assert kinds[1] in REFUSING, kinds
    assert kinds[2] in REFUSING, kinds


def test_a_command_the_client_would_run_is_held_to_the_list_too(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    _review(
        record,
        worktree,
        specs,
        act=[
            {"terminal": "git", "args": ["log", "--oneline"]},
            {"terminal": "touch", "args": ["written"]},
            {"write": str(worktree / "written"), "content": "x\n"},
        ],
    )

    ran, touched = requests(record, "did/terminal")
    assert "error" not in ran, ran
    assert "error" in touched, touched
    assert not (worktree / "written").exists()
    [wrote] = requests(record, "did/write")
    assert "error" in wrote, wrote


def test_the_run_says_once_that_read_only_holds_only_for_what_is_asked(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    lines: list[str] = []

    _review(
        tmp_path / "agent.jsonl",
        worktree,
        specs,
        lines,
        act=[{"ask": "execute", "command": "git status"}, {"ask": "execute", "command": "git log"}],
    )

    told = [line for line in lines if "read-only" in line and "without asking" in line]
    assert len(told) == 1, lines
    assert not [line for line in lines if "ignored" in line], lines


def test_a_build_mode_run_is_not_held_read_only(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    lines: list[str] = []
    use_agent(
        record,
        act=[
            {"ask": "edit", "paths": [str(worktree / "src" / "app.py")]},
            {"ask": "execute", "command": "git status"},
        ],
    )

    AcpRuntime().run(
        AgentRequest(
            prompt="Build.",
            role="implement",
            cwd=worktree,
            allowed_tools="Read Edit Write Grep Glob Bash(git *)",
            permission_mode="edit",
            policy=ToolPolicy(specs_dir=specs),
            on_event=lines.append,
        )
    )

    kinds = [answer["optionKind"] for answer in _asked(record)]
    assert kinds == ["allow_once", "allow_once"], kinds
    assert not [line for line in lines if "read-only" in line], lines


def test_a_review_that_edits_without_asking_fails_naming_the_change(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    edited = str(worktree / "src" / "app.py")

    result = _review(record, worktree, specs, act=[{"edit": edited, "content": "MARKER = 1\n"}])

    assert requests(record, "did/edit") != []
    assert result.ok is False
    assert "src/app.py" in result.error
    assert "changed the worktree" in result.error


def test_a_review_that_adds_a_file_without_asking_fails_naming_it(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    result = _review(
        record, worktree, specs, act=[{"edit": str(worktree / "new.txt"), "content": "x\n"}]
    )

    assert result.ok is False
    assert "new.txt" in result.error


def test_a_review_that_changes_nothing_still_succeeds(
    tmp_path: Path, worktree: Path, specs: Path
) -> None:
    record = tmp_path / "agent.jsonl"

    result = _review(
        record, worktree, specs, act=[{"ask": "execute", "command": "git diff main...HEAD"}]
    )

    assert result.ok is True
    assert result.error == ""
