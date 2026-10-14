"""`abk init` run with its prompts, agents and OpenSpec replaced, over one repo
with code: for tests of one step of the command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import init as init_cmd
from agent_build_kit.init.detect import Host
from tests.factories import git, init_repo


def fake_openspec(argv, *, cwd, **kwargs):
    args = argv[len(openspec.command()) :]
    if args[0] == "init":
        (cwd / "openspec" / "changes" / "archive").mkdir(parents=True)
        (cwd / "openspec" / "specs").mkdir()
        (cwd / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
        return subprocess.CompletedProcess(argv, 0, "", "")
    if args[0] == "validate":
        return subprocess.CompletedProcess(argv, 0, json.dumps({"items": []}), "")
    return subprocess.CompletedProcess(argv, 0, "", "")


def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        init_cmd, "which", lambda program: "/bin/claude" if program == "claude" else None
    )
    monkeypatch.setattr(init_cmd, "run_openspec", fake_openspec)
    monkeypatch.setattr(init_cmd, "ask", lambda prompt: pytest.fail("prompted unexpectedly"))
    monkeypatch.setattr(init_cmd, "host", lambda: Host.OTHER)
    monkeypatch.setattr(
        init_cmd, "run_fix", lambda argv, **kwargs: pytest.fail(f"ran a fix unasked: {argv}")
    )


def app_repo(root: Path) -> Path:
    repo = init_repo(root / "app")
    git(repo, "remote", "add", "origin", "git@github.com:example/app.git")
    (repo / "pyproject.toml").write_text('[project]\nname = "app"\n')
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "code")
    return repo
