"""The gate lines of `abk status`: provider, amounts, percent, reset, threshold now, state and
where the figure came from (spec: split-gate-usage, "The status and the doctor show a split's gate
usage")."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as pipeline_cli
from agent_build_kit.pipeline.e2e_holds import SOURCE_GATE, write_hold
from agent_build_kit.pipeline.usage_guard import GATE_USAGE_NAME
from tests.cli.e2e_hold_fakes import abk, planning
from tests.cli.gate_usage_fakes import (
    Reads,
    command_gate,
    gated_planning,
    month_end,
    provider_gate,
    provider_reads,
)
from tests.gate_hold_support import Probe


@pytest.fixture(autouse=True)
def no_claude_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)


def gate_lines(config: Path, capsys: pytest.CaptureFixture[str], *flags: str) -> list[str]:
    code, out, err = abk(config, capsys, "status", *flags)
    assert code == 0, err
    return [line for line in out if line.startswith("gate usage:")]


def test_a_split_over_its_threshold_shows_the_figures_the_threshold_the_reset_and_the_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads("173.04285316"))
    config = gated_planning(tmp_path, provider_gate())
    gate_lines(config, capsys, "--refresh")

    (line,) = gate_lines(config, capsys)

    assert line.startswith("gate usage: acp (modal) 173.04 of 200 USD (87%), threshold 70%, ")
    assert f"resets {month_end():%m-%d} 00:00 UTC" in line
    assert re.search(r"held \(provider reading, \d+m old\)$", line), line


def test_a_threshold_that_is_moving_shows_what_it_moves_towards_and_when(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads("100"))
    config = gated_planning(
        tmp_path, provider_gate("{usage_pause_ceiling_pct: 90, usage_relief_fraction: 1}")
    )
    gate_lines(config, capsys, "--refresh")

    (line,) = gate_lines(config, capsys)

    assert re.search(r"ramping to 90% by \d\d-\d\d \d\d:\d\d", line), line


def test_a_split_with_room_says_usable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads("80"))
    config = gated_planning(tmp_path, provider_gate())
    gate_lines(config, capsys, "--refresh")

    (line,) = gate_lines(config, capsys)

    assert "(40%)" in line and "usable" in line and "held" not in line


def test_an_unknown_result_says_unknown_with_its_reason_and_never_usable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads(error=RuntimeError("no login configured")))
    config = gated_planning(tmp_path, provider_gate())
    gate_lines(config, capsys, "--refresh")

    (line,) = gate_lines(config, capsys)

    assert "unknown" in line and "RuntimeError: no login configured" in line
    assert "usable" not in line


def test_a_split_held_by_hand_shows_that_source_and_not_the_gates_figures_as_the_cause(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads("80"))
    config = gated_planning(tmp_path, provider_gate())
    assert abk(config, capsys, "e2e-test", "hold", "acp", "--reason", "by hand")[0] == 0
    gate_lines(config, capsys, "--refresh")

    (line,) = gate_lines(config, capsys)

    assert "held" in line and "command" in line
    assert "usable" not in line


def test_a_command_gate_shows_its_result_and_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = gated_planning(tmp_path, command_gate(Probe(tmp_path / "bin", "acp", 3)))
    gate_lines(config, capsys, "--refresh")

    (line,) = gate_lines(config, capsys)

    assert line.startswith("gate usage: acp (command)")
    assert "held" in line and "quota spent" in line
    assert re.search(r"\(command result, \d+m old\)", line), line


def test_only_a_split_with_a_gate_gets_a_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads())
    config = gated_planning(tmp_path, provider_gate())

    (line,) = gate_lines(config, capsys, "--refresh")

    assert "acp" in line and "claude_code" not in line


def test_status_runs_no_command_without_refresh_and_one_with_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    probe = Probe(tmp_path / "bin", "acp", 3)
    config = gated_planning(tmp_path, command_gate(probe))

    (unread,) = gate_lines(config, capsys)
    assert probe.runs == 0
    assert "unknown" in unread and "usable" not in unread

    gate_lines(config, capsys, "--refresh")
    assert probe.runs == 1
    gate_lines(config, capsys)
    assert probe.runs == 1


def test_status_asks_no_provider_without_refresh_and_one_with_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    reads = provider_reads(monkeypatch, Reads())
    config = gated_planning(tmp_path, provider_gate())

    gate_lines(config, capsys)
    assert reads.calls == 0

    gate_lines(config, capsys, "--refresh")
    assert reads.calls == 1


def test_a_reading_older_than_the_cache_still_shows_with_its_age_while_the_hold_stands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider_reads(monkeypatch, Reads("173.04285316"))
    config = gated_planning(tmp_path, provider_gate())
    gate_lines(config, capsys, "--refresh")
    cache = config.parent / GATE_USAGE_NAME
    body = json.loads(cache.read_text())
    taken = datetime.fromisoformat(body["acp"]["taken_at"]) - timedelta(minutes=20)
    body["acp"]["taken_at"] = taken.isoformat()
    cache.write_text(json.dumps(body))
    write_hold(
        config.parent,
        "acp",
        reason="modal usage 173.04 of 200 USD",
        source=SOURCE_GATE,
        by="gate evaluation",
        until=month_end(),
        now=datetime.now(UTC),
    )

    (line,) = gate_lines(config, capsys)

    assert "173.04 of 200 USD (87%)" in line and "not read yet" not in line
    assert re.search(r"held \(provider reading, (2\d)m old\)$", line), line


def test_a_workspace_with_no_gate_has_no_gate_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gate_lines(planning(tmp_path), capsys, "--refresh") == []
