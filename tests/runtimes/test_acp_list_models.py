"""Listing an agent's models from what it advertises when a session opens: no prompt."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.runtimes import acp
from agent_build_kit.runtimes.base import Model, ModelSource
from tests.runtimes.acp_agent import requests, use_agent


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
