"""A call on the Claude Code runtime hands its caller how full the context window was
(`AgentResult.context`): per request, from the assistant events of the stream (spec:
usage-accounting, Every agent call records its context window use in tokens).

The `claude` process is faked at its boundary with the stream-json a real run prints. What was
confirmed against recorded streams: each assistant event carries its request's usage, repeated
by every content block of the request; a compaction prints a `system` event with subtype
`compact_boundary` and a `compactMetadata` naming the tokens before and after; a result's
`modelUsage` entry carries token counts and cost, and a `contextWindow` only on some versions
(the recorded one has none, so the configured table is what names the window there).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.usage import ContextBasis
from tests.conftest import make_installation
from tests.runtimes.claude_cli import (
    COMPACT_BOUNDARY,
    MODEL,
    FakeClaude,
    requests_filling,
)

K = 1000


def run(tmp_path: Path, stdout: str) -> AgentResult:
    request = AgentRequest(prompt="Implement group 1.", role="implement", cwd=tmp_path, model=MODEL)
    return ClaudeCodeRuntime(execute=FakeClaude(stdout=stdout)).run(request)


def test_the_fill_follows_each_requests_input_cache_read_and_cache_creation(
    tmp_path: Path,
) -> None:
    result = run(
        tmp_path, requests_filling(tmp_path, 150 * K, 170 * K, 195 * K, blocks=2, window=200 * K)
    )

    context = result.context
    assert context is not None
    assert context.used_start == 150 * K
    assert context.used_end == 195 * K
    assert context.peak == 195 * K
    assert context.added == 45 * K
    assert context.compactions == 0
    assert context.basis == ContextBasis.REPORTED


def test_a_request_repeated_by_its_content_blocks_counts_once(tmp_path: Path) -> None:
    once = run(tmp_path, requests_filling(tmp_path, 150 * K, 195 * K, 80 * K, blocks=1))
    thrice = run(tmp_path, requests_filling(tmp_path, 150 * K, 195 * K, 80 * K, blocks=3))

    assert once.context is not None
    assert once.context.compactions == 1
    assert thrice.context == once.context


def test_a_sub_agents_requests_are_not_the_main_context(tmp_path: Path) -> None:
    result = run(tmp_path, requests_filling(tmp_path, 150 * K, (20 * K, True), 170 * K))

    context = result.context
    assert context is not None
    assert context.used_start == 150 * K
    assert context.used_end == 170 * K
    assert context.peak == 170 * K
    assert context.compactions == 0, "the sub-agent's small context is no drop in the main one"


def test_the_window_is_the_one_the_result_names(tmp_path: Path) -> None:
    make_installation(
        tmp_path / "planning", runtimes={"claude_code": {"context_windows": {MODEL: 200 * K}}}
    )

    result = run(tmp_path, requests_filling(tmp_path, 150 * K, window=1000 * K))

    assert result.context is not None
    assert result.context.max == 1000 * K, "the result's own figure is read before the table"
    assert result.context.basis == ContextBasis.REPORTED


def test_a_result_without_a_window_takes_the_configured_tables_figure(tmp_path: Path) -> None:
    make_installation(
        tmp_path / "planning", runtimes={"claude_code": {"context_windows": {MODEL: 200 * K}}}
    )

    result = run(tmp_path, requests_filling(tmp_path, 150 * K))

    assert result.context is not None
    assert result.context.max == 200 * K


def test_a_window_of_the_wrong_type_reads_as_absent_and_the_call_still_succeeds(
    tmp_path: Path,
) -> None:
    make_installation(
        tmp_path / "planning", runtimes={"claude_code": {"context_windows": {MODEL: 200 * K}}}
    )

    result = run(tmp_path, requests_filling(tmp_path, 150 * K, window="a lot"))

    assert result.ok
    assert result.context is not None
    assert result.context.max == 200 * K


def test_a_window_neither_the_result_nor_the_table_names_is_absent_and_unknown(
    tmp_path: Path,
) -> None:
    result = run(tmp_path, requests_filling(tmp_path, 150 * K))

    assert result.ok
    assert result.context is not None
    assert result.context.max is None
    assert result.context.basis == ContextBasis.UNKNOWN


def test_a_run_with_no_per_request_usage_reports_no_context(tmp_path: Path) -> None:
    result = run(tmp_path, "the answer, as plain -p prints it\n")

    assert result.ok
    assert result.context is None


def test_a_fall_in_the_fill_larger_than_the_share_of_the_window_is_one_compaction(
    tmp_path: Path,
) -> None:
    result = run(tmp_path, requests_filling(tmp_path, 150 * K, 195 * K, 80 * K, window=200 * K))

    context = result.context
    assert context is not None
    assert context.compactions == 1
    assert context.added == 0, "a step that shrank added nothing"
    assert context.peak == 195 * K
    assert context.used_end == 80 * K
    assert context.used_start == 150 * K


def test_a_smaller_fall_is_no_compaction(tmp_path: Path) -> None:
    result = run(tmp_path, requests_filling(tmp_path, 150 * K, 195 * K, 170 * K, window=200 * K))

    assert result.context is not None
    assert result.context.compactions == 0
    assert result.context.added == 20 * K


def test_the_share_that_makes_a_fall_a_compaction_is_configured(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning", context={"compaction_drop_share": 0.1})

    result = run(tmp_path, requests_filling(tmp_path, 150 * K, 195 * K, 170 * K, window=200 * K))

    assert result.context is not None
    assert result.context.compactions == 1


def test_the_runtimes_own_marker_is_counted_instead_of_the_fall(tmp_path: Path) -> None:
    result = run(
        tmp_path,
        requests_filling(tmp_path, 150 * K, 195 * K, COMPACT_BOUNDARY, 80 * K, window=200 * K),
    )

    assert result.context is not None
    assert result.context.compactions == 1, "the marker and the fall are one compaction"


def test_a_marker_counts_even_when_the_fill_fell_less_than_the_share(tmp_path: Path) -> None:
    result = run(
        tmp_path,
        requests_filling(tmp_path, 150 * K, 195 * K, COMPACT_BOUNDARY, 170 * K, window=200 * K),
    )

    assert result.context is not None
    assert result.context.compactions == 1


@pytest.mark.parametrize("window", [None, 200 * K])
def test_a_run_that_compacts_twice_counts_both(tmp_path: Path, window: int | None) -> None:
    make_installation(
        tmp_path / "planning", runtimes={"claude_code": {"context_windows": {MODEL: 200 * K}}}
    )

    result = run(
        tmp_path,
        requests_filling(tmp_path, 190 * K, 60 * K, 190 * K, 60 * K, window=window),
    )

    assert result.context is not None
    assert result.context.compactions == 2
