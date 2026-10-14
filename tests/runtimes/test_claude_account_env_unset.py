"""With no account set nothing is added: each kind of call hands over the environment it handed
over before, and the same call with an account holds that environment plus the variable and
nothing else (spec: claude-account)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.claude_account import VARIABLE
from agent_build_kit.config import models
from agent_build_kit.pipeline.wiring import build_run
from tests.conftest import make_installation
from tests.runtimes.account_calls import KINDS, use_account
from tests.runtimes.stand_in import StandInRuntime


@pytest.mark.parametrize("kind", list(KINDS))
def test_an_account_adds_the_variable_to_what_the_call_was_given_and_nothing_else(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_account(monkeypatch, None)
    without = KINDS[kind](tmp_path / "unset")
    use_account(monkeypatch, tmp_path / "account")
    with_account = KINDS[kind](tmp_path / "set")

    assert without is None or VARIABLE not in without
    assert with_account == {**(without or {}), VARIABLE: str(tmp_path / "account")}


def test_a_request_on_a_runtime_that_is_not_claude_code_carries_no_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The account is the Claude Code runtime's to add, so the request the wiring builds has
    none; and the same account set makes no difference to it."""
    planning = tmp_path / "planning"
    make_installation(planning)
    use_account(monkeypatch, None)
    unset = StandInRuntime(answer="built it")
    build_run(runtime=unset, planning_repo=planning)("Go.", cwd=tmp_path, model=models().implement)
    use_account(monkeypatch, tmp_path / "account")
    stand_in = StandInRuntime(answer="built it")
    build_run(runtime=stand_in, planning_repo=planning)(
        "Go.", cwd=tmp_path, model=models().implement
    )

    assert VARIABLE not in stand_in.request.env
    assert stand_in.request.env == unset.request.env
    # The runtime that does add it is what makes the setting reach a `claude`.
    env = KINDS["build"](tmp_path)
    assert env is not None and env[VARIABLE] == str(tmp_path / "account")
