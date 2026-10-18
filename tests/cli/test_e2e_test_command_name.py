"""`abk e2e-test` is the command; the old command still works as a deprecated alias."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.e2e_hold_fakes import abk, planning

OLD_COMMAND = "tier" + "2"
NOTICE = f"command `{OLD_COMMAND}` is deprecated; use `e2e-test`"


def test_the_new_name_runs_with_no_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)

    code, _, err = abk(config, capsys, "e2e-test", "status")

    assert code == 0
    assert not any(NOTICE in line for line in err)


def test_the_old_name_runs_and_says_it_is_deprecated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planning(tmp_path)

    code, _, err = abk(config, capsys, OLD_COMMAND, "status")

    assert code == 0
    assert any(NOTICE in line for line in err)
