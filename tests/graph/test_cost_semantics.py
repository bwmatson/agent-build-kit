"""What the ledger records of a call's cost: its own spend, the session's running total and how
the first was obtained (spec: agent-usage-capture, Every agent call records its own cost and
its session's running total).

The runtime is the real Claude Code one over a faked `claude` process printing the stream a
real run does, or a runtime behind the seam reporting a running total as ACP does; the ledger
is read back from disk as the report reads it.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import pytest

from agent_build_kit.graph.state import SessionRole
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_ledger import CostBasis, read_ledger
from agent_build_kit.pipeline.wiring import build_run, build_run_review
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.settings import settings
from tests.fake_gateway import MASTER, serving
from tests.graph.cost_fakes import BUILD_SESSION, Cumulative, Metered
from tests.graph.test_build_path import build, restacked
from tests.graph.test_session_continuation import reuse
from tests.graph_driver import fresh, position, tick
from tests.ledger_lines import costed_line, write_ledger
from tests.runner_fakes import Killed, approving
from tests.runtimes.claude_cli import FakeClaude, finished_build


def agents(tmp_path: Path, build_claude: FakeClaude) -> dict:
    review = FakeClaude(stdout=finished_build(tmp_path, approving()))
    return dict(
        run=build_run(runtime=ClaudeCodeRuntime(execute=build_claude)),
        run_review=build_run_review(runtime=ClaudeCodeRuntime(execute=review), model="m"),
    )


def lines(workspace: Installation, node: str | None = None) -> list[dict]:
    path = workspace.state_dir / "usage-ledger.jsonl"
    if not path.exists():
        return []
    every = [json.loads(line) for line in path.read_text().splitlines() if line]
    return [x for x in every if x.get("kind", "agent") == "agent" and node in (None, x["node"])]


def cost_of(line: dict) -> dict:
    return line.get("cost") or {}


# --- the Claude Code runtime ------------------------------------------------------------


def test_a_sessions_first_call_records_its_total_as_both_figures_and_a_resumed_one_the_difference(
    tmp_path: Path, workspace: Installation
) -> None:
    reuse(build=True)

    tick(tmp_path, fresh(tmp_path), **agents(tmp_path, Metered([2.63, 5.49])))

    (tests,) = lines(workspace, "tests")
    assert cost_of(tests)["incremental_usd"] == pytest.approx(2.63)
    assert cost_of(tests)["cumulative_usd"] == pytest.approx(2.63)
    assert cost_of(tests)["basis"] == CostBasis.FIRST
    (implement,) = lines(workspace, "implement")
    assert implement["session_id"] == BUILD_SESSION
    assert cost_of(implement)["incremental_usd"] == pytest.approx(2.86)
    assert cost_of(implement)["cumulative_usd"] == pytest.approx(5.49)
    assert cost_of(implement)["basis"] == CostBasis.DERIVED


def test_a_record_carries_no_flat_cost_beside_the_object(
    tmp_path: Path, workspace: Installation
) -> None:
    tick(tmp_path, fresh(tmp_path), **agents(tmp_path, Metered([2.63, 5.49])))

    written = lines(workspace)
    assert written
    for line in written:
        assert "cost_usd" not in line
        assert "reported_cost_usd" not in line
        assert "cost" in line


def test_the_increments_of_a_sessions_calls_sum_to_its_final_cumulative(
    tmp_path: Path, workspace: Installation
) -> None:
    reuse(build=True)

    tick(tmp_path, fresh(tmp_path), **agents(tmp_path, Metered([2.63, 5.49])))

    records = read_ledger(workspace.state_dir / "usage-ledger.jsonl")
    ours = [r.cost for r in records if r.role != "review" and r.cost is not None]
    assert len(ours) == 2
    assert sum(c.incremental_usd or 0 for c in ours) == pytest.approx(5.49)
    assert ours[-1].cumulative_usd == pytest.approx(5.49)


def test_a_total_below_the_baseline_starts_a_new_baseline_and_the_reset_is_noted(
    tmp_path: Path, workspace: Installation
) -> None:
    reuse(build=True)
    recorder = fresh(tmp_path)

    tick(tmp_path, recorder, **agents(tmp_path, Metered([10.0, 1.2])))

    (implement,) = lines(workspace, "implement")
    assert cost_of(implement)["incremental_usd"] == pytest.approx(1.2)
    assert cost_of(implement)["cumulative_usd"] == pytest.approx(1.2)
    assert any("reset" in line.lower() for line in recorder.logged)


def test_a_figure_the_runtime_does_not_report_is_absent_and_never_zero(
    tmp_path: Path, workspace: Installation
) -> None:
    silent = FakeClaude(stdout="the answer, as plain -p prints it\n")

    tick(tmp_path, fresh(tmp_path), **agents(tmp_path, silent))

    written = lines(workspace, "tests")
    assert written
    for line in written:
        assert "cost_usd" not in line
        assert cost_of(line).get("incremental_usd") is None
        assert cost_of(line).get("cumulative_usd") is None


# --- the baseline's sources -------------------------------------------------------------


def test_the_recorded_session_carries_its_cumulative_figure_to_the_next_call(
    tmp_path: Path, workspace: Installation
) -> None:
    reuse(build=True)

    tick(tmp_path, fresh(tmp_path), **agents(tmp_path, Metered([2.63, 5.49])))

    state = position(tmp_path).state
    assert state is not None
    assert state.sessions[SessionRole.BUILD].cumulative_usd == pytest.approx(5.49)


def test_a_call_killed_and_resumed_derives_its_spend_from_the_session_recorded_before_it(
    tmp_path: Path, workspace: Installation
) -> None:
    reuse(build=True)
    recorder = fresh(tmp_path)
    run = agents(tmp_path, Metered([2.63, 5.49], die_on=2))
    with pytest.raises(Killed):
        tick(tmp_path, recorder, **run)

    tick(tmp_path, recorder, **run)

    (implement,) = lines(workspace, "implement")
    assert implement["resumed"] is True
    assert cost_of(implement)["incremental_usd"] == pytest.approx(2.86)
    assert cost_of(implement)["cumulative_usd"] == pytest.approx(5.49)
    assert cost_of(implement)["basis"] == CostBasis.DERIVED


def test_a_resume_with_no_recorded_baseline_reads_the_last_ledger_record_of_the_session(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    with pytest.raises(Killed):
        tick(tmp_path, recorder, **agents(tmp_path, Metered([5.0, 6.0], die_on=1)))
    write_ledger(
        workspace.state_dir / "usage-ledger.jsonl",
        costed_line(3.0, 3.0, basis="first", session_id=BUILD_SESSION, node="tests"),
    )

    tick(tmp_path, recorder, **agents(tmp_path, Metered([5.0, 6.0])))

    resumed = [x for x in lines(workspace, "tests") if x.get("resumed")]
    assert len(resumed) == 1
    assert cost_of(resumed[0])["incremental_usd"] == pytest.approx(2.0)
    assert cost_of(resumed[0])["cumulative_usd"] == pytest.approx(5.0)
    assert cost_of(resumed[0])["basis"] == CostBasis.DERIVED


def test_a_resume_with_no_baseline_anywhere_is_unknown_and_never_the_total(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    with pytest.raises(Killed):
        tick(tmp_path, recorder, **agents(tmp_path, Metered([5.0, 6.0], die_on=1)))

    tick(tmp_path, recorder, **agents(tmp_path, Metered([5.0, 6.0])))

    resumed = [x for x in lines(workspace, "tests") if x["resumed"]]
    assert len(resumed) == 1
    assert cost_of(resumed[0])["basis"] == CostBasis.UNKNOWN
    assert cost_of(resumed[0]).get("incremental_usd") is None
    assert cost_of(resumed[0])["cumulative_usd"] == pytest.approx(5.0)


def test_the_session_a_port_ran_in_carries_its_cumulative_figure_to_the_follow_up(
    tmp_path: Path, workspace: Installation
) -> None:
    reuse(build=True)
    recorder = fresh(tmp_path)
    conflicts = iter([restacked(conflict="x", old_tests=("test_click",))] * 2)

    with contextlib.suppress(Exception):
        build(
            tmp_path,
            recorder,
            base="spec/c/2",
            branch_commits=lambda cwd, base: recorder.made,
            restack_onto=lambda **kw: next(conflicts, None),
            reset_to=lambda tree, onto, keep: None,
            tests_in=lambda tree: set(),
            tests_changed=lambda tree, ref: set(),
            **agents(tmp_path, Metered([2.0, 3.0, 4.5, 5.0])),
        )

    adapt = lines(workspace, "adapt")
    assert [cost_of(x).get("incremental_usd") for x in adapt] == pytest.approx([1.5, 0.5])
    assert [cost_of(x).get("cumulative_usd") for x in adapt] == pytest.approx([4.5, 5.0])


# --- runtimes reporting a running total of their own ------------------------------------


def test_a_runtime_reporting_a_running_total_gets_first_then_derived(
    tmp_path: Path, workspace: Installation
) -> None:
    reuse(build=True)
    runtime = Cumulative([0.31, 0.81])

    tick(tmp_path, fresh(tmp_path), run=build_run(runtime=runtime))

    (tests,) = lines(workspace, "tests")
    assert cost_of(tests)["cumulative_usd"] == pytest.approx(0.31)
    assert cost_of(tests)["incremental_usd"] == pytest.approx(0.31)
    assert cost_of(tests)["basis"] == CostBasis.FIRST
    (implement,) = lines(workspace, "implement")
    assert cost_of(implement)["cumulative_usd"] == pytest.approx(0.81)
    assert cost_of(implement)["incremental_usd"] == pytest.approx(0.5)
    assert cost_of(implement)["basis"] == CostBasis.DERIVED


# --- gateway-attributed runs --------------------------------------------------------------


def test_a_gateway_attributed_call_records_the_gateways_figure_and_keeps_the_runtimes_apart(
    tmp_path: Path, workspace: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    reuse(build=True)
    with serving() as gateway:
        monkeypatch.setattr(settings, "gateway_url", gateway.url)
        monkeypatch.setattr(settings, "gateway_master_key", MASTER)
        monkeypatch.setattr(settings, "gateway_settle_seconds", 0.1)

        tick(tmp_path, fresh(tmp_path), run=build_run(runtime=Cumulative([0.4, 1.1], gateway)))

    (tests,) = lines(workspace, "tests")
    assert tests["usage_source"] == "gateway"
    assert cost_of(tests)["incremental_usd"] == pytest.approx(0.5)
    assert cost_of(tests)["cumulative_usd"] == pytest.approx(0.5)
    assert cost_of(tests)["basis"] == CostBasis.REPORTED
    assert cost_of(tests)["reported_usd"] == pytest.approx(0.4)
    (implement,) = lines(workspace, "implement")
    assert cost_of(implement)["incremental_usd"] == pytest.approx(1.0)
    assert cost_of(implement)["cumulative_usd"] == pytest.approx(1.5), (
        "the session's records so far"
    )
    assert cost_of(implement)["basis"] == CostBasis.REPORTED
    assert cost_of(implement)["reported_usd"] == pytest.approx(0.7), "the runtime's own increase"
    assert "reported_cost_usd" not in implement


def test_a_call_cut_off_by_the_usage_limit_leaves_its_total_as_the_baseline_of_the_one_resuming_it(
    tmp_path: Path, workspace: Installation
) -> None:
    reuse(build=True)
    recorder = fresh(tmp_path)
    with contextlib.suppress(Exception):
        tick(tmp_path, recorder, **agents(tmp_path, Metered([2.63, 5.49], limited_on=2)))

    tick(tmp_path, recorder, **agents(tmp_path, Metered([6.00, 7.00])))

    implement = lines(workspace, "implement")
    assert [cost_of(x)["cumulative_usd"] for x in implement] == pytest.approx([5.49, 6.00])
    assert [cost_of(x)["incremental_usd"] for x in implement] == pytest.approx([2.86, 0.51])
    assert cost_of(implement[-1])["basis"] == CostBasis.DERIVED
    session = [x for x in lines(workspace) if x["session_id"] == BUILD_SESSION]
    assert sum(cost_of(x)["incremental_usd"] for x in session) == pytest.approx(6.00)
