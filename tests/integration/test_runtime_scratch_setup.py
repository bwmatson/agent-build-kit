"""The scratch setup of a live test is chosen by runtime, and each runtime parameter has one tag."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

from agent_build_kit import claude_account
from tests.agent_home import HOME_VAR
from tests.runtime_scratch import RUNTIME_PARAMS, RUNTIMES, runtime_scratch

pytestmark = pytest.mark.integration

AGENT_COMMAND = "ABK_ACCEPTANCE_ACP_COMMAND"


class Factory:
    def __init__(self, root: Path) -> None:
        self.root = root

    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        path = self.root / basename
        path.mkdir()
        return path


@pytest.fixture(autouse=True)
def no_agent_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOME_VAR, raising=False)


def test_acp_gets_a_runtimes_entry_and_the_override_from_the_agent_command_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = "some-agent --stdio 'a b'"
    monkeypatch.setenv(AGENT_COMMAND, line)
    checked: list[list[str]] = []

    scratch = runtime_scratch("acp", Factory(tmp_path), checked.append)

    expected = shlex.split(line)
    assert yaml.safe_load(scratch.runtimes_yaml) == {"runtimes": {"acp": {"command": expected}}}
    assert scratch.env["ABK_RUNTIME"] == "acp"
    assert scratch.command == expected
    assert checked == [expected]


def test_claude_code_gets_no_entry_and_pins_the_runtime_and_sets_its_account_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = tmp_path / "account"
    account.mkdir()
    monkeypatch.setenv(claude_account.VARIABLE, str(account))

    scratch = runtime_scratch("claude_code", Factory(tmp_path), lambda command: None)

    assert scratch.runtimes_yaml == ""
    assert scratch.env["ABK_RUNTIME"] == "claude_code"
    assert scratch.env[claude_account.VARIABLE] == str(account)


def test_acp_without_a_command_fails_naming_the_setting_and_does_not_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(AGENT_COMMAND, raising=False)

    with pytest.raises(pytest.fail.Exception, match=AGENT_COMMAND):
        runtime_scratch("acp", Factory(tmp_path), lambda command: None)


def test_each_runtime_parameter_has_exactly_one_tag_named_for_its_runtime() -> None:
    assert [p.values[0] for p in RUNTIME_PARAMS] == list(RUNTIMES)
    for param in RUNTIME_PARAMS:
        tags = [m.name for m in param.marks if m.name.startswith("runtime_")]
        assert tags == [f"runtime_{param.values[0]}"]
