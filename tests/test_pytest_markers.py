"""The e2e marker the acceptance tests carry: registered, kept out of the
default run, and documented beside the marker already there."""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

import pytest

from tests.child_pytest import run_scenario

ROOT = Path(__file__).resolve().parents[1]


def pytest_options() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]


def default_deselection() -> str:
    """The `-m` expression of the kit's default run."""
    words = shlex.split(pytest_options()["addopts"])
    return words[words.index("-m") + 1]


def test_the_e2e_marker_is_registered() -> None:
    markers = pytest_options()["markers"]

    assert any(marker.startswith("e2e:") for marker in markers)


def test_the_old_marker_name_is_not_registered() -> None:
    markers = pytest_options()["markers"]

    assert any(marker.startswith("e2e:") for marker in markers)
    assert not any(marker.startswith("local_stack") for marker in markers)


def test_the_default_run_excludes_it_and_the_integration_tier() -> None:
    addopts = pytest_options()["addopts"]

    assert "not e2e" in addopts
    assert "not integration" in addopts
    assert "local_stack" not in addopts


def test_the_default_run_deselects_the_same_tests_as_before(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_scenario(
        pytester,
        "default_deselection",
        "marked_kinds.py",
        "--collect-only",
        "-m",
        default_deselection(),
        monkeypatch=monkeypatch,
    )

    assert re.findall(r"marked_kinds\.py::(\w+)", run.output) == ["test_plain"], run.output


def test_the_script_that_runs_them_is_named_for_the_marker() -> None:
    text = (ROOT / "pyproject.toml").read_text()

    assert re.search(r'^test-e2e = "pytest -m e2e"$', text, re.MULTILINE)
    assert "test-local-stack" not in text


def test_the_docs_describe_it_beside_the_integration_marker() -> None:
    for path in (ROOT / "docs" / "agent-runtimes.md", ROOT / "AGENTS.md"):
        text = " ".join(path.read_text().split())

        assert "pytest -m e2e" in text, path
        assert "local_stack" not in text, path
