"""`abk init` run with its prompts, agents and OpenSpec replaced, over one repo
with code: for tests of one step of the command."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.init.detect import Host
from tests.factories import fake_openspec, git, init_repo


def claude_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine whose path holds `claude` and no other known agent."""
    monkeypatch.setattr(
        init_cmd, "which", lambda program: "/bin/claude" if program == "claude" else None
    )


def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    claude_only(monkeypatch)
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
