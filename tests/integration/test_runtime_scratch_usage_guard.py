"""The scratch setup of a live test starts its tick with the usage guard off unless it opts in."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from tests.agent_home import HOME_VAR
from tests.integration.test_runtime_scratch_setup import Factory
from tests.runtime_scratch import runtime_scratch

pytestmark = pytest.mark.integration

AGENT_COMMAND = "ABK_ACCEPTANCE_ACP_COMMAND"
GUARD = "ABK_USAGE_GUARD"


@pytest.fixture(autouse=True)
def no_agent_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOME_VAR, raising=False)
    monkeypatch.delenv(GUARD, raising=False)


def test_claude_code_has_the_guard_off_unless_it_opts_in_and_acp_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "in").mkdir()
    (tmp_path / "acp").mkdir()
    scratch = runtime_scratch("claude_code", Factory(tmp_path), lambda command: None)
    assert scratch.env[GUARD] == "off"
    assert scratch.runtimes_yaml == ""
    assert scratch.env["ABK_RUNTIME"] == "claude_code"

    opted_in = runtime_scratch(
        "claude_code", Factory(tmp_path / "in"), lambda command: None, usage_guard=True
    )
    assert GUARD not in opted_in.env

    monkeypatch.setenv(AGENT_COMMAND, "some-agent --stdio")
    command = shlex.split("some-agent --stdio")
    acp = runtime_scratch("acp", Factory(tmp_path / "acp"), lambda command: None)
    assert GUARD not in acp.env
    assert acp.runtimes_yaml == f"runtimes:\n  acp:\n    command: {command}\n"


def test_a_value_set_in_the_test_process_is_overridden_by_the_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GUARD, "on")

    scratch = runtime_scratch("claude_code", Factory(tmp_path), lambda command: None)

    assert scratch.env[GUARD] == "off"
