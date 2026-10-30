"""The kit's pytest keeps only the temp folders of failed tests, and only a few runs of them."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAX_RETENTION_COUNT = 3


def pytest_options() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]


def test_a_passing_tests_temp_folder_is_not_kept() -> None:
    assert pytest_options().get("tmp_path_retention_policy") == "failed"


def test_the_retention_count_is_at_most_three() -> None:
    count = int(pytest_options()["tmp_path_retention_count"])

    assert 0 <= count <= MAX_RETENTION_COUNT
