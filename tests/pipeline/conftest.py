"""Fixtures shared by the pipeline tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline import spans


@pytest.fixture
def scratch(tmp_path: Path) -> Iterator[Path]:
    """A checkout of a python project with two test files, the unit `add-marker/1` running in it
    (see `tests/failure_bundle_fakes.py` for the machine that answers there)."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0"\ndependencies = ["pytest-xdist"]\n'
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_gone.py").write_text("")
    (tmp_path / "tests" / "test_kept.py").write_text("")
    token = spans.current_unit.set(("add-marker/1", "add-marker", "n1", 1))
    yield tmp_path
    spans.current_unit.reset(token)
