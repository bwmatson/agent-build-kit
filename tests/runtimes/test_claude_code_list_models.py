"""Claude Code has no command that lists models: its list is the documented aliases."""

from __future__ import annotations

import asyncio
import subprocess

import pytest

from agent_build_kit.runtimes import claude_code
from agent_build_kit.runtimes.base import ModelSource


def test_the_documented_aliases_are_listed_and_said_to_be_documented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("listing started an agent")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)

    listed = claude_code.RUNTIME.list_models()

    assert listed.source == ModelSource.DOCUMENTED
    assert "documented" in listed.note
    names = {model.name for model in listed.models}
    defaults = claude_code.RUNTIME.default_models
    assert names
    assert {defaults.implement, defaults.review} <= names
