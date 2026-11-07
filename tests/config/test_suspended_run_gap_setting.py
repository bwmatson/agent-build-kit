"""`global_limits.suspended_run_gap_seconds`: the gap between a run's wall time and its own
duration above which the run counts as one the machine was suspended in (spec:
suspended-check-run)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config


def write(tmp_path: Path, block: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(f"version: 1\nglobal_limits:\n{block}")
    return path


def test_the_gap_defaults_to_300_seconds(tmp_path: Path) -> None:
    limits = config.load(write(tmp_path, "  max_flakes_per_run: 5\n")).global_limits

    assert limits.model_dump()["suspended_run_gap_seconds"] == 300


def test_a_gap_above_zero_is_kept(tmp_path: Path) -> None:
    limits = config.load(write(tmp_path, "  suspended_run_gap_seconds: 0.5\n")).global_limits

    assert limits.model_dump()["suspended_run_gap_seconds"] == 0.5


@pytest.mark.parametrize("value", [0, -1])
def test_a_gap_that_is_not_above_zero_is_refused_by_name(tmp_path: Path, value: int) -> None:
    with pytest.raises(config.ConfigError, match=r"global_limits\.suspended_run_gap_seconds"):
        config.load(write(tmp_path, f"  suspended_run_gap_seconds: {value}\n"))
