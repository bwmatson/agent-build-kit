"""Fixtures the runtimes' tests share."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.factories import init_repo


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    """Where `doctor` and `init` ask from: the planning checkout, which the
    probe must leave as it found it."""
    root = init_repo(tmp_path / "planning")
    (root / "abk.yaml").write_text("repos: {}\n")
    return root
