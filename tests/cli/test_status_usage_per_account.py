"""`abk status` prints one usage line per account in use (spec: claude-accounts, usage and slots
are per account).

An account is in use when a repo resolves to it; a label with no directory on this machine is the
default account, so an installation with one account prints the one line it printed before.
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.claude_account import resolve
from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_allowances import allowances_path, write_allowances
from tests.conftest import make_installation
from tests.usage_allowance_records import calibrated
from tests.usage_host import Host, editor_block

MINUTE = timedelta(minutes=1)


def installation(tmp_path: Path, host: Host, *, directory: Path | None) -> Installation:
    """`app` on the default account and `platform` on the label `kit`, which names `directory`
    on this machine when one is given."""
    kit = {} if directory is None else {"config_dir": str(directory)}
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        repos={
            "app": {"path": str(tmp_path / "app"), "slug": "example/app"},
            "platform": {
                "path": str(tmp_path / "platform"),
                "slug": "example/platform",
                "account": "kit",
            },
        },
        runtimes={"claude_code": {"accounts": {"kit": kit}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    return inst


def usage_lines(inst: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0
    return [each for each in capsys.readouterr().out.splitlines() if "usage: " in each]


def test_a_second_account_in_use_gets_its_own_usage_line_and_one_account_one_line(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    one = installation(tmp_path / "alone", host, directory=None)
    (alone,) = usage_lines(one, capsys)
    assert "kit" not in alone

    directory = tmp_path / "second-claude"
    directory.mkdir()
    (directory / ".claude.json").write_text(
        json.dumps(editor_block(6 * MINUTE, session=33, resets_in=timedelta(hours=2)))
    )
    inst = installation(tmp_path, host, directory=directory)

    lines = usage_lines(inst, capsys)

    assert len(lines) == 2
    (second,) = [each for each in lines if "kit" in each]
    assert "claude.json" in second
    (default,) = [each for each in lines if "kit" not in each]
    assert "unknown" in default


def test_the_allowances_line_of_each_account_comes_from_its_own_file_and_is_marked(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "second-claude"
    directory.mkdir()
    inst = installation(tmp_path, host, directory=directory)
    write_allowances(
        allowances_path(inst.state_dir, resolve(inst, "kit")), {"weekly": calibrated(4)}
    )

    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0

    lines = [each for each in capsys.readouterr().out.splitlines() if "usage allowances" in each]
    assert len(lines) == 2
    (second,) = [each for each in lines if "account kit" in each]
    assert "weekly 4/unit" in second
    (default,) = [each for each in lines if "account kit" not in each]
    assert "weekly 4/unit" not in default
