"""`abk status` shows each account's login: when its token expires, or that it has, and the age
of the last real usage reading (spec: claude-steps-can-renew-their-login).

The status showed a reading's age and source but never the token's expiry, so a login that was
about to lapse, or that had lapsed with no usage read to notice it, looked like any other."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from tests.conftest import make_installation
from tests.usage_host import Host, payload


def keep_token(expires_in: timedelta | None) -> None:
    """The default account's credentials file, with a token that expires `expires_in` from now."""
    folder = Path.home() / ".claude"
    folder.mkdir(parents=True, exist_ok=True)
    document: dict = {"claudeAiOauth": {"accessToken": "x"}}
    if expires_in is not None:
        document["claudeAiOauth"]["expiresAt"] = int(
            (datetime.now(UTC) + expires_in).timestamp() * 1000
        )
    (folder / ".credentials.json").write_text(json.dumps(document))


def status(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str], *, read: int | None
) -> str:
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    if read is not None:
        host.keep_reading(timedelta(minutes=read), payload(session=0.0, weekly=10.0))

    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0

    return capsys.readouterr().out


def login_line(out: str) -> str:
    (line,) = [line for line in out.splitlines() if "login:" in line]
    return line


def test_a_live_token_says_when_it_expires_and_in_how_long(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    keep_token(timedelta(hours=4, minutes=47, seconds=30))

    line = login_line(status(tmp_path, host, capsys, read=None))

    assert re.search(r"token expires \d\d:\d\dZ \(in 4h47m\)", line)


def test_an_expired_token_says_it_has_expired(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    keep_token(-timedelta(minutes=12, seconds=30))

    line = login_line(status(tmp_path, host, capsys, read=None))

    assert "token expired 12m ago" in line


def test_a_token_whose_expiry_cannot_be_read_says_so(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    keep_token(None)

    line = login_line(status(tmp_path, host, capsys, read=None))

    assert "token expiry unknown" in line


def test_the_line_gives_the_age_of_the_last_real_usage_reading(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    keep_token(timedelta(hours=2))

    line = login_line(status(tmp_path, host, capsys, read=89))

    assert "last real usage read 89m ago" in line


def test_the_line_says_when_no_usage_reading_has_been_made(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    keep_token(timedelta(hours=2))

    line = login_line(status(tmp_path, host, capsys, read=None))

    assert "no real usage read yet" in line
