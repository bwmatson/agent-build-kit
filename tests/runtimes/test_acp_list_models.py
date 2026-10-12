"""Listing an agent's models from what it advertises when a session opens: no prompt."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import acp
from agent_build_kit.runtimes.base import Model, ModelSource
from tests.runtimes.acp_agent import command, requests, use_agent


def test_the_advertised_models_are_listed_with_the_current_one_marked(tmp_path: Path) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, models=("m-one", "m-two", "m-three"), fail="error")

    listed = acp.RUNTIME.list_models()

    assert listed.source == ModelSource.ADVERTISED
    assert listed.models == (
        Model(name="m-one", current=True),
        Model(name="m-two"),
        Model(name="m-three"),
    )
    assert len(requests(record, "session/new")) == 1
    assert requests(record, "session/prompt") == []


def test_an_agent_that_advertises_none_gives_an_empty_list_and_says_so(tmp_path: Path) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, models=(), fail="error")

    listed = acp.RUNTIME.list_models()

    assert listed.models == ()
    assert listed.source == ModelSource.NONE
    assert "model" in listed.note
    assert requests(record, "session/prompt") == []


def test_a_command_given_is_the_one_asked_and_the_configured_one_is_not(tmp_path: Path) -> None:
    configured = tmp_path / "configured.jsonl"
    given = tmp_path / "given.jsonl"
    use_agent(configured, models=("old-1",))

    listed = acp.RUNTIME.list_models(command(given, models=("new-1", "new-2")))

    assert [m.name for m in listed.models] == ["new-1", "new-2"]
    assert len(requests(given, "session/new")) == 1
    assert requests(configured, "session/new") == []


def test_an_agent_that_never_opens_a_session_is_given_up_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, fail="session")
    monkeypatch.setattr(acp, "LISTING_TIMEOUT", 1)

    listed = acp.RUNTIME.list_models()

    assert listed.models == ()
    assert listed.source == ModelSource.NONE
    assert "did not answer" in listed.note
