"""`abk status` says that an account's login is rejected after a refresh (spec: login-refresh).

The line gives the command to sign in again, with the account's directory when it has one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.usage_host import Host, reject_login, rejection


def installation(tmp_path: Path, host: Host, *, labelled: bool) -> Installation:
    repo = {"path": str(tmp_path / "app"), "slug": "example/app"}
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        repos={"app": {**repo, "account": "kit"} if labelled else repo},
        runtimes={"claude_code": {"accounts": {"kit": {"config_dir": str(tmp_path / "kit-home")}}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    return inst


def rejected_lines(inst: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0
    return [each for each in capsys.readouterr().out.splitlines() if "login is rejected" in each]


def test_a_labelled_accounts_status_names_the_rejected_login_and_its_directory(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host, labelled=True)
    kit = claude_account.resolve(inst, "kit")
    reject_login(host, kit)

    (line,) = rejected_lines(inst, capsys)

    assert rejection(kit) in line


def test_the_default_accounts_status_gives_the_command_without_a_directory(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host, labelled=False)
    default = claude_account.resolve(inst, None)
    reject_login(host, default)

    (line,) = rejected_lines(inst, capsys)

    assert rejection(default) in line
    assert "CLAUDE_CONFIG_DIR" not in line
