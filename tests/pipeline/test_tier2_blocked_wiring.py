"""The runner `build_runner` assembles runs tier 2 with the blocked runtimes left out, and
hands the node the run's result and the blocks (spec: tier2-runtime-parking)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import wiring
from tests.pipeline.test_e2e_split_groups import (
    FILES,
    MARKER,
    SOURCE,
    Groups,
    expected,
    expression_of,
)
from tests.pipeline.test_tier2_gate_wiring import runner_of
from tests.tier2_scope_fakes import branch

REASON = "the provider is down"


def test_the_runner_reports_the_blocks_of_the_configuration_and_the_file(tmp_path: Path) -> None:
    built, _, _ = runner_of(
        tmp_path, blocked_in_config=("claude_code",), blocked_in_file={"acp": REASON}
    )

    blocked = built.e2e_holds().held

    assert set(blocked) == {"acp", "claude_code"}
    assert blocked["acp"].reason == REASON


def test_a_run_through_the_runner_leaves_the_blocked_runtime_out_and_reports_it_parked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = Groups()
    # The session takes the command runner when the runner is built.
    monkeypatch.setattr(wiring, "_run", ran)
    built, _, _ = runner_of(tmp_path, scope="full", blocked_in_file={"acp": REASON})
    repo, base = branch(tmp_path, SOURCE, base_files=FILES)

    ok, _ = built.run_e2e(cwd=repo, base=base)

    assert ok
    assert {expression_of(command) for command in ran.runs} == {expected(["acp"])}
    result = built.e2e_result()
    assert result is not None and result.parked == ["acp"]


def test_a_run_through_the_runner_with_nothing_blocked_parks_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = Groups()
    monkeypatch.setattr(wiring, "_run", ran)
    built, _, _ = runner_of(tmp_path, scope="full")
    repo, base = branch(tmp_path, SOURCE, base_files=FILES)

    built.run_e2e(cwd=repo, base=base)

    assert {expression_of(command) for command in ran.runs} == {MARKER}
    result = built.e2e_result()
    assert result is not None and result.parked == []
