"""The retry layer's settings: the deadline is new, the attempts come from `forge_retries`."""

from __future__ import annotations

import pytest

from agent_build_kit.settings import Settings


def test_the_deadline_defaults_to_two_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ABK_FORGE_DEADLINE_SECONDS", raising=False)

    assert getattr(Settings(_env_file=None), "forge_deadline_seconds", None) == 120.0


def test_the_deadline_is_set_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABK_FORGE_DEADLINE_SECONDS", "45")

    assert getattr(Settings(_env_file=None), "forge_deadline_seconds", None) == 45.0
