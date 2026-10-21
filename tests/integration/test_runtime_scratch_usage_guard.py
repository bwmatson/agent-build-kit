"""The scratch setup of a live test starts its tick with the usage guard off unless it opts in."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.agent_home import HOME_VAR
from tests.integration.test_runtime_scratch_setup import Factory
from tests.runtime_scratch import AGENT_COMMAND, RUNTIME_PARAMS, runtime_scratch

pytestmark = pytest.mark.integration

GUARD = "ABK_USAGE_GUARD"
# What each runtime's setup puts in the guard variable by default; None leaves it unset.
DEFAULT_GUARD = {"claude_code": "off", "acp": None}


@pytest.fixture(autouse=True)
def no_agent_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOME_VAR, raising=False)
    monkeypatch.delenv(GUARD, raising=False)
    monkeypatch.setenv(AGENT_COMMAND, "some-agent --stdio")


@pytest.mark.parametrize("runtime", RUNTIME_PARAMS)
def test_the_guard_is_off_by_default_only_where_the_setup_says_and_opting_in_leaves_it_alone(
    runtime: str, tmp_path: Path
) -> None:
    (tmp_path / "in").mkdir()
    scratch = runtime_scratch(runtime, Factory(tmp_path), lambda command: None)
    assert scratch.env.get(GUARD) == DEFAULT_GUARD[runtime]
    assert scratch.env["ABK_RUNTIME"] == runtime

    opted_in = runtime_scratch(
        runtime, Factory(tmp_path / "in"), lambda command: None, usage_guard=True
    )
    assert GUARD not in opted_in.env


@pytest.mark.parametrize("runtime", RUNTIME_PARAMS)
def test_a_value_set_in_the_test_process_is_overridden_by_the_setup(
    runtime: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(GUARD, "on")

    scratch = runtime_scratch(runtime, Factory(tmp_path), lambda command: None)

    assert scratch.env.get(GUARD) == DEFAULT_GUARD[runtime]
