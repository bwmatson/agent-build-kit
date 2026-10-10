"""What the ledger records of a call's context window use: the runtime's figures, written to
the call's line as the `context` object, and the run unaffected when it reports none (spec:
usage-accounting, Every agent call records its context window use in tokens).

The runtime is the real Claude Code one over a faked `claude` process printing the stream a
real run does; the ledger is read back from disk as the report reads it.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.wiring import build_run, build_run_review
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.usage import ContextBasis
from tests.graph.test_cost_semantics import lines
from tests.graph_driver import fresh, tick
from tests.runner_fakes import approving
from tests.runtimes.claude_cli import FakeClaude, finished_build, requests_filling

K = 1000


def agents(build: FakeClaude, tmp_path: Path) -> dict:
    review = FakeClaude(stdout=finished_build(tmp_path, approving()))
    return dict(
        run=build_run(runtime=ClaudeCodeRuntime(execute=build)),
        run_review=build_run_review(runtime=ClaudeCodeRuntime(execute=review), model="m"),
    )


def test_a_calls_line_carries_the_context_object_the_runtime_reported(
    tmp_path: Path, workspace: Installation
) -> None:
    build = FakeClaude(stdout=requests_filling(tmp_path, 150 * K, 170 * K, 195 * K, window=200 * K))

    tick(tmp_path, fresh(tmp_path), **agents(build, tmp_path))

    written = lines(workspace, "tests")
    assert written
    for line in written:
        context = line["context"]
        assert context["used_start"] == 150 * K
        assert context["used_end"] == 195 * K
        assert context["added"] == 45 * K
        assert context["peak"] == 195 * K
        assert context["compactions"] == 0
        assert context["max"] == 200 * K
        assert context["basis"] == ContextBasis.REPORTED


def test_a_call_that_reported_no_context_is_recorded_unknown_with_no_figures(
    tmp_path: Path, workspace: Installation
) -> None:
    silent = FakeClaude(stdout="the answer, as plain -p prints it\n")

    tick(tmp_path, fresh(tmp_path), **agents(silent, tmp_path))

    written = lines(workspace, "tests")
    assert written
    for line in written:
        context = line["context"]
        assert context["basis"] == ContextBasis.UNKNOWN
        for figure in ("used_start", "used_end", "added", "peak", "max"):
            assert context.get(figure) is None


def test_a_step_that_ends_above_the_warning_share_warns_once_and_the_run_goes_on(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    build = FakeClaude(stdout=requests_filling(tmp_path, 150 * K, 190 * K, window=200 * K))

    tick(tmp_path, recorder, **agents(build, tmp_path))

    warned = [line for line in recorder.logged if "context" in line.lower() and "190" in line]
    built = lines(workspace, "tests") + lines(workspace, "implement")
    assert built
    assert len(warned) == len(built), "one warning for each step that ended near the limit"
    assert lines(workspace, "review"), "nothing was scheduled or stopped from the warning"
