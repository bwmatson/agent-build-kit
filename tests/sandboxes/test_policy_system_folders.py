"""A policy built with no grants of its own still reads the system folders, so the launcher can
exec a program (spec: product-defects, group 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.sandboxes.base import system_folders
from tests.sandboxes.policy_support import Scene


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return Scene(tmp_path)


def test_an_empty_sandbox_block_still_reads_the_system_folders(scene: Scene) -> None:
    policy = scene.policy({})

    assert {Path(folder).resolve() for folder in system_folders()} <= set(policy.read)
