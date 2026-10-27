"""Run a scenario folder of `tests/child_modules/` as a child pytest."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from agent_build_kit.model import Frozen


class ChildRun(Frozen):
    code: int
    output: str


def run_scenario(
    pytester: pytest.Pytester,
    scenario: str,
    module: str,
    *args: str,
    env: Mapping[str, str] = {},
    monkeypatch: pytest.MonkeyPatch,
) -> ChildRun:
    raise NotImplementedError
