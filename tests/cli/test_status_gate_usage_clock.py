"""The gate lines of `abk status` at a moment the test chooses: the line is a function of the
clock `spans.clock` gives, so the figures, the threshold now and the age of the reading never
depend on when, or how slowly, the suite runs (spec: test-determinism)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as pipeline_cli
from tests.cli.e2e_hold_fakes import abk
from tests.cli.gate_usage_fakes import Reads, gated_planning, provider_gate, provider_reads
from tests.fake_clock import FakeClock, install
from tests.provider_summaries import summary

# A month that is not the one the machine is in, so a clock that is not the fake one shows.
MONTH_START = datetime(2030, 1, 1, tzinfo=UTC)
MONTH_END = datetime(2030, 2, 1, tzinfo=UTC)
HALFWAY = datetime(2030, 1, 16, 12, 0, tzinfo=UTC)


class JanuaryReads(Reads):
    """The provider's reading for January 2030, whatever the clock says."""

    def __call__(self) -> object:
        self.calls += 1
        return summary(start=MONTH_START, end=MONTH_END, metered_cost=Decimal(self.cost))


@pytest.fixture(autouse=True)
def no_claude_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch, HALFWAY)


def gate_line(config: Path, capsys: pytest.CaptureFixture[str], *flags: str) -> str:
    code, out, err = abk(config, capsys, "status", *flags)
    assert code == 0, err
    (line,) = [line for line in out if line.startswith("gate usage:")]
    return line


def test_a_split_over_its_threshold_shows_its_figures_and_the_age_the_clock_gives(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
) -> None:
    provider_reads(monkeypatch, JanuaryReads("173.04285316"))
    config = gated_planning(tmp_path, provider_gate())
    gate_line(config, capsys, "--refresh")
    clock.advance(7 * 60)

    line = gate_line(config, capsys)

    assert line == (
        "gate usage: acp (modal) 173.04 of 200 USD (87%), threshold 70%, "
        "resets 02-01 00:00 UTC, held (provider reading, 7m old)"
    )


def test_a_threshold_that_is_moving_is_the_one_the_clock_gives(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
) -> None:
    provider_reads(monkeypatch, JanuaryReads("100"))
    config = gated_planning(
        tmp_path, provider_gate("{usage_pause_ceiling_pct: 90, usage_relief_fraction: 1}")
    )
    gate_line(config, capsys, "--refresh")

    line = gate_line(config, capsys)

    # Halfway through a month whose whole length is the ramp: 70 + (90 - 70) / 2.
    assert f"threshold 80%, ramping to 90% by {MONTH_END.astimezone():%m-%d %H:%M}" in line


def test_a_split_with_room_says_usable_with_the_age_the_clock_gives(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    clock: FakeClock,
) -> None:
    provider_reads(monkeypatch, JanuaryReads("80"))
    config = gated_planning(tmp_path, provider_gate())
    gate_line(config, capsys, "--refresh")
    clock.advance(3 * 60)

    line = gate_line(config, capsys)

    assert line == (
        "gate usage: acp (modal) 80.00 of 200 USD (40%), threshold 70%, "
        "resets 02-01 00:00 UTC, usable (provider reading, 3m old)"
    )
