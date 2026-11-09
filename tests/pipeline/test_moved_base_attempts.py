"""A moved-base run the lane starts is one attempt at the tip of the unit's base
(spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.moved_base_attempts_scene import Attempts

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Attempts:
    return Attempts(tmp_path, monkeypatch)
