from __future__ import annotations

from pathlib import Path

import pytest

from tests.tick_driver import Setup, make_setup


@pytest.fixture
def graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    """A tick over one unit's thread with its edges faked (`tests/tick_driver.py`)."""
    return make_setup(tmp_path, monkeypatch)
