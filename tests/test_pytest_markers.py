"""The tier-2 marker the acceptance tests carry: registered, kept out of the
default run, and documented beside the marker already there."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pytest_options() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]


def test_the_tier2_marker_is_registered() -> None:
    markers = pytest_options()["markers"]

    assert any(marker.startswith("local_stack:") for marker in markers)


def test_the_default_run_excludes_it_and_the_integration_tier() -> None:
    addopts = pytest_options()["addopts"]

    assert "not local_stack" in addopts
    assert "not integration" in addopts


def test_the_docs_describe_it_beside_the_integration_marker() -> None:
    for path in (ROOT / "docs" / "agent-runtimes.md", ROOT / "CLAUDE.md"):
        text = " ".join(path.read_text().split())

        assert "local_stack" in text, path
        assert "pytest -m local_stack" in text, path
