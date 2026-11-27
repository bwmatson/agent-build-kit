"""The machine sample over a folder laid out as `/proc` (spec: test-failure-evidence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.failure_evidence import machine_sample

MEMINFO = (
    "MemTotal:       16000000 kB\n"
    "MemFree:         1000000 kB\n"
    "MemAvailable:    8000000 kB\n"
    "SwapTotal:       4000000 kB\n"
    "SwapFree:        1500000 kB\n"
)
PRESSURE = (
    "some avg10=0.00 avg60=0.00 avg300=0.00 total=123456\n"
    "full avg10=0.00 avg60=0.00 avg300=0.00 total=7890\n"
)


def _proc(root: Path, meminfo: str | None = MEMINFO, pressure: str | None = PRESSURE) -> Path:
    if meminfo is not None:
        (root / "meminfo").write_text(meminfo)
    if pressure is not None:
        (root / "pressure").mkdir()
        (root / "pressure" / "memory").write_text(pressure)
    return root


def test_a_sample_holds_the_memory_available_the_swap_used_and_the_full_pressure_total(
    tmp_path: Path,
) -> None:
    sample = machine_sample(_proc(tmp_path))

    assert sample.get("memory_available_kb") == 8000000
    assert sample.get("swap_used_kb") == 4000000 - 1500000
    assert sample.get("memory_pressure_full_us") == 7890


def test_a_folder_without_pressure_gives_the_memory_and_swap_and_no_pressure(
    tmp_path: Path,
) -> None:
    sample = machine_sample(_proc(tmp_path, pressure=None))

    assert sample.get("memory_available_kb") == 8000000
    assert sample.get("swap_used_kb") == 2500000
    assert "memory_pressure_full_us" not in sample


@pytest.mark.parametrize(
    "meminfo",
    [None, "MemTotal: 1 kB\nMemAvailable:    8000000 kB\n"],
    ids=["no meminfo", "no swap lines"],
)
def test_a_missing_meminfo_or_swap_lines_leave_those_readings_out_and_keep_load_and_cpus(
    tmp_path: Path, meminfo: str | None
) -> None:
    sample = machine_sample(_proc(tmp_path, meminfo=meminfo))

    assert "swap_used_kb" not in sample
    assert ("memory_available_kb" in sample) == (meminfo is not None)
    assert sample.get("memory_pressure_full_us") == 7890
    assert sample.get("cpus")
    assert "load" in sample


@pytest.mark.parametrize(
    "pressure",
    ["", "garbage\n", "some total=1\n", "full avg10=0.00 total=abc\n"],
    ids=["empty", "garbage", "no full line", "bad number"],
)
def test_a_pressure_file_that_does_not_parse_is_left_out_and_not_raised(
    tmp_path: Path, pressure: str
) -> None:
    sample = machine_sample(_proc(tmp_path, pressure=pressure))

    assert "memory_pressure_full_us" not in sample
    assert sample.get("swap_used_kb") == 2500000
