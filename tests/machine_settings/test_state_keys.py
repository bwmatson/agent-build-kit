"""The planning home and the state directory are machine facts when they leave the repository
(spec: planning-state-home)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.machine_settings import machine_settings
from tests.config_migrate_machine_support import TILDE


def listed(document: dict[str, Any], top: Path) -> list[tuple[str, ...]]:
    return [s.path for s in machine_settings(document, top) if s.kind == "machine"]


@pytest.mark.parametrize("value", ["state-home", f"{TILDE}planning", "/srv/planning"])
def test_the_home_is_always_a_machine_fact(tmp_path: Path, value: str) -> None:
    assert listed({"planning": {"home": value}}, tmp_path / "plan") == [("planning", "home")]


@pytest.mark.parametrize(
    "value", [f"{TILDE}s", "/srv/state", "../state"], ids=["tilde", "absolute", "outside"]
)
def test_a_state_dir_that_leaves_the_repository_is_a_machine_fact(
    tmp_path: Path, value: str
) -> None:
    found = listed({"planning": {"state_dir": value}}, tmp_path / "plan")

    assert found == [("planning", "state_dir")]
