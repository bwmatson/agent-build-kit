"""A call made at a site outside the unit graph writes exactly one row with its node name, over the
Claude runtime (a faked `claude` process) and the ACP runtime (a small agent speaking the protocol
on stdio), and the guard over the real source passes with an empty allowlist (spec:
usage-accounting, every agent call writes exactly one row).
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from agent_build_kit.init.research import research
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planner import PlannerError, plan_round
from agent_build_kit.runtimes import AgentRuntime
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.tracks import runner
from tests.agent_call_sites import SRC_ROOT, check_sources
from tests.call_rows import agent_rows
from tests.pipeline.test_planner_runtime import CHANGES, IN_FLIGHT, PLAN
from tests.runtimes.acp_agent import use_agent
from tests.runtimes.claude_cli import FakeClaude, record
from tests.tracks.test_runner import project

CLAUDE = "claude_code"
ACP = "acp"


def runtime_of(kind: str, tmp_path: Path, stdout: str) -> AgentRuntime:
    if kind == CLAUDE:
        return ClaudeCodeRuntime(execute=FakeClaude(stdout=stdout))
    use_agent(tmp_path / "agent.jsonl")
    return AcpRuntime()


def plan(runtime: AgentRuntime, tmp_path: Path, inst: Installation) -> None:
    # An ACP agent's words are not a plan; the call was made and its row written either way.
    with contextlib.suppress(PlannerError):
        plan_round(changes=CHANGES, in_flight=IN_FLIGHT, runtime=runtime)


def init_research(runtime: AgentRuntime, tmp_path: Path, inst: Installation) -> None:
    research(
        "python",
        built_in="seed",
        output=tmp_path / "python.md",
        runtime=runtime,
        today=date(2030, 1, 2),
    )


def health(runtime: AgentRuntime, tmp_path: Path, inst: Installation) -> None:
    app = project(inst)
    app.path.mkdir(parents=True)
    runner.claude_phase(inst, project=app, name="health", runtime=runtime)


SITES: dict[str, tuple[str, str, Callable[[AgentRuntime, Path, Installation], None]]] = {
    "plan": ("plan", json.dumps(PLAN), plan),
    "init_research": ("init_research", "## Formatting\n\n- rule\n", init_research),
    "track_health": ("track_health", record("done"), health),
}


# Research asks for web tools, which the ACP runtime refuses to run without a way to hold them.
CASES = [
    (kind, site)
    for site in sorted(SITES)
    for kind in (CLAUDE, ACP)
    if (kind, site) != (ACP, "init_research")
]


@pytest.mark.parametrize(("kind", "site"), CASES)
def test_a_call_at_the_site_writes_exactly_one_row_named_for_it(
    tmp_path: Path, workspace: Installation, kind: str, site: str
) -> None:
    node, stdout, call = SITES[site]
    runtime = runtime_of(kind, tmp_path, stdout)

    call(runtime, tmp_path, workspace)

    rows = agent_rows(workspace)
    assert [row["node"] for row in rows] == [node]
    assert rows[0]["runtime"] == kind


def test_the_guard_passes_over_the_real_source_with_an_empty_allowlist() -> None:
    assert check_sources(SRC_ROOT, allowlist={}) == []
