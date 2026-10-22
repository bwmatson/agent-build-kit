"""The scratch setup of a live test is chosen by runtime, and each runtime parameter has one tag."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
import yaml

from agent_build_kit import claude_account
from tests.agent_home import HOME_VAR
from tests.runtime_scratch import AGENT_COMMAND, RUNTIME_PARAMS, RUNTIMES, runtime_scratch

pytestmark = pytest.mark.integration

LINE = "some-agent --stdio 'a b'"


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


@pytest.mark.parametrize("runtime", RUNTIME_PARAMS)
def test_each_runtime_gets_its_entry_and_pins_the_runtime_and_its_agent(
    runtime: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    account = tmp_path / "account"
    account.mkdir()
    monkeypatch.setenv(claude_account.VARIABLE, str(account))
    monkeypatch.setenv(AGENT_COMMAND, LINE)
    checked: list[list[str]] = []
    command = shlex.split(LINE)
    expected = {
        "acp": {
            "runtimes_yaml": {"runtimes": {"acp": {"command": command}}},
            "command": command,
            "checked": [command],
            "account": None,
        },
        "claude_code": {
            "runtimes_yaml": None,
            "command": [],
            "checked": [],
            "account": str(account),
        },
    }[runtime]

    scratch = runtime_scratch(runtime, Factory(tmp_path), checked.append)

    assert (yaml.safe_load(scratch.runtimes_yaml) or None) == expected["runtimes_yaml"]
    assert scratch.env["ABK_RUNTIME"] == runtime
    assert scratch.command == expected["command"]
    assert checked == expected["checked"]
    assert scratch.env.get(claude_account.VARIABLE) == expected["account"]


@pytest.mark.parametrize("runtime", RUNTIME_PARAMS)
def test_a_missing_agent_command_fails_naming_the_setting_only_where_the_runtime_needs_it(
    runtime: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(AGENT_COMMAND, raising=False)

    if runtime == "acp":
        with pytest.raises(pytest.fail.Exception, match=AGENT_COMMAND):
            runtime_scratch(runtime, Factory(tmp_path), lambda command: None)
    else:
        assert runtime_scratch(runtime, Factory(tmp_path), lambda command: None).command == []


@pytest.mark.parametrize("runtime", RUNTIME_PARAMS)
def test_the_runtime_parameter_has_exactly_one_tag_named_for_its_runtime(
    runtime: str, request: pytest.FixtureRequest
) -> None:
    assert runtime in RUNTIMES
    tags = [m.name for m in request.node.iter_markers() if m.name.startswith("runtime_")]
    assert tags == [f"runtime_{runtime}"]
