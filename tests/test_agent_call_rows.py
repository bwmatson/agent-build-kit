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
from typing import Any, cast

import pytest

from agent_build_kit.init.propose import propose
from agent_build_kit.init.research import research
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planner import PlannerError, plan_round
from agent_build_kit.runtimes import AgentRequest, AgentResult, AgentRuntime
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.tracks import runner
from tests.agent_call_sites import SRC_ROOT, check_sources
from tests.call_rows import agent_rows
from tests.factories import init_repo
from tests.init.test_propose import detection, valid_report, write_change
from tests.pipeline.test_planner_runtime import CHANGES, IN_FLIGHT, PLAN
from tests.pipeline.test_restack_conflict_rows import conflicting, move
from tests.runtimes.acp_agent import use_agent
from tests.runtimes.claude_cli import FakeClaude, record
from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracks.test_runner import project

CLAUDE = "claude_code"
ACP = "acp"


class Counting:
    """A runtime that counts the calls it was asked to make, so a site that retries (the
    conflict resolver, when nothing is resolved) is held to one row per call."""

    def __init__(self, inner: AgentRuntime) -> None:
        self.inner = inner
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def run(self, request: AgentRequest) -> AgentResult:
        self.calls += 1
        return self.inner.run(request)


def runtime_of(kind: str, tmp_path: Path, stdout: str) -> Counting:
    if kind == CLAUDE:
        return Counting(ClaudeCodeRuntime(execute=FakeClaude(stdout=stdout)))
    use_agent(tmp_path / "agent.jsonl")
    return Counting(AcpRuntime())


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


def init_propose(runtime: AgentRuntime, tmp_path: Path, inst: Installation) -> None:
    # The change is on disk before the call, so one attempt validates and none is repaired.
    planning = init_repo(tmp_path / "planning")
    (planning / "openspec" / "changes").mkdir(parents=True)
    write_change(planning, "app-testing-infrastructure")
    propose(
        "app",
        detection(init_repo(tmp_path / "app")),
        planning=planning,
        recommendations=planning / "none.md",
        kind="testing-infrastructure",
        run_openspec=valid_report(planning),
        repos=("platform", "app"),
        runtime=runtime,
    )


def restack(runtime: AgentRuntime, tmp_path: Path, inst: Installation) -> None:
    # The fake agents resolve nothing; the resolver is called once and its row is written.
    with contextlib.suppress(Exception):
        move(conflicting(tmp_path / "repo"), runtime)


SITES: dict[str, tuple[str, str, Callable[[AgentRuntime, Path, Installation], None]]] = {
    "plan": ("plan", json.dumps(PLAN), plan),
    "init_research": ("init_research", "## Formatting\n\n- rule\n", init_research),
    "init_propose": ("init_propose", "done", init_propose),
    "track_health": ("track_health", record("done"), health),
    "restack": ("restack", "done", restack),
}


# Research asks for web tools, which the ACP runtime refuses to run without a way to hold them.
# `login_refresh` exists on Claude Code only: it is covered by
# tests/runtimes/test_login_refresh_row.py. A chat turn
# and the attach flow's fix turn need the server and run over both runtimes in
# tests/serve/test_chat_rows_runtimes.py.
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

    call(cast(AgentRuntime, runtime), tmp_path, workspace)

    rows = agent_rows(workspace)
    assert runtime.calls >= 1
    assert [row["node"] for row in rows] == [node] * runtime.calls
    assert {row["runtime"] for row in rows} == {kind}


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_the_guard_passes_over_the_real_source_with_an_empty_allowlist() -> None:
    assert check_sources(SRC_ROOT, allowlist={}) == []
