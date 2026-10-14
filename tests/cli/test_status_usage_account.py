"""`abk status` names the account its usage line belongs to (spec: usage-account).

With an account set the line ends with the reading's source and age and then names the
directory, and `usage: unknown` says whose reading is missing; with none set the lines are
the ones printed before.
"""

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.usage_host import Host, editor_block

MINUTE = timedelta(minutes=1)


def installation(tmp_path: Path, host: Host) -> Installation:
    inst = make_installation(
        tmp_path / "planning", planning={"state_dir": "."}, runtimes={"claude_code": {}}
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    return inst


def usage_lines(inst: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0
    return [each for each in capsys.readouterr().out.splitlines() if "usage: " in each]


def test_a_reading_is_followed_by_its_source_and_age_and_then_the_account(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host)
    host.keep_editor_reading(6 * MINUTE)
    (before,) = [each for each in usage_lines(inst, capsys) if "claude.json" in each]
    assert before.endswith("(claude.json, 6m old)")

    account = host.use_account(
        block=editor_block(6 * MINUTE, session=33, resets_in=timedelta(hours=2))
    )
    (line,) = [each for each in usage_lines(inst, capsys) if "claude.json" in each]

    assert "(claude.json, 6m old)" in line
    assert line.index(str(account)) > line.index("6m old)")
    assert line.count("m old") == 1


def test_with_no_reading_it_says_unknown_and_names_the_account(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host)
    assert [each.endswith("usage: unknown") for each in usage_lines(inst, capsys)] == [True]

    account = host.use_account()
    lines = usage_lines(inst, capsys)

    (unknown,) = [each for each in lines if "usage: unknown" in each]
    assert str(account) in unknown
