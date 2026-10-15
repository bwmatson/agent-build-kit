"""A fake `claude auth status` for `abk doctor`: the exit status and JSON object the real one
answers with, and the environment each call was made in."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.account_settings import Configure
from tests.cli.test_doctor import Answers
from tests.factories import which_all

VARIABLE = "CLAUDE_CONFIG_DIR"


class FakeClaude(Answers):
    """`Answers` that also answers `<claude> auth status --json` with `status` and `body`
    (plus whatever `extra` keys a real answer carries) and keeps each such call."""

    def __init__(self, *, status: int = 0, logged_in: bool = True, extra: dict | None = None):
        super().__init__()
        self.status = status
        self.body = {"loggedIn": logged_in, **(extra or {})}
        self.asked: list[tuple[list[str], dict[str, str] | None]] = []

    def __call__(self, argv, **kwargs):
        if list(argv[-3:]) == ["auth", "status", "--json"]:
            self.asked.append((list(argv), kwargs.get("env")))
            return subprocess.CompletedProcess(argv, self.status, json.dumps(self.body), "")
        return super().__call__(argv, **kwargs)


def account_lines(workspace: Path, run: Answers) -> list[Check]:
    """The checks doctor adds for the account."""
    checks = run_doctor(workspace / "abk.yaml", run=run, which=which_all)
    return [check for check in checks if "account" in check.name]


def said(checks: list[Check]) -> str:
    """Everything the checks print."""
    return "\n".join(f"{c.name} {c.status} {c.detail} {c.fix}" for c in checks)


def in_planning_env(workspace: Path, configure: Configure, **settings: dict[str, str]) -> None:
    """Configure the process and `.env` as `configure` does, with the `.env` the planning
    repo's own, which is the one doctor reads."""
    (workspace / ".env").write_text(configure(**settings).read_text())
