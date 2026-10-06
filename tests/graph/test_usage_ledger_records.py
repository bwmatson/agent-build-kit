"""Each agent call of a unit's thread leaves one record in the usage ledger,
`<state_dir>/usage-ledger.jsonl`, naming where it was made and what the runtime
reported; and nothing the ledger does can fail a run (spec: agent-usage-capture).

The agent is the real Claude Code runtime behind `build_run_claude` and
`build_run_review`, with the `claude` process faked at its boundary.
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.usage_ledger import read_ledger
from agent_build_kit.pipeline.wiring import build_run_claude, build_run_review
from agent_build_kit.runtimes import AgentRequest, AgentResult
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.factories import unit
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Killed, approving
from tests.runtimes.claude_cli import SESSION, FakeClaude, finished_build
from tests.runtimes.stand_in import StandInRuntime

BUILD_MODEL = "build-model"
REVIEW_MODEL = "review-model"


class Silent(StandInRuntime):
    """A runtime that reports nothing about what it spent, and says it finished."""

    name = "silent"

    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        if request.on_result is not None:
            request.on_result(result)
        return result


class KilledInImplement(StandInRuntime):
    """A runtime that numbers its sessions, reports each call it finishes, and
    dies in the second call (the implement node) once it has announced its session."""

    name = "killable"
    supports_session_resume = True
    passes_env = False

    def __init__(self) -> None:
        super().__init__(answer="done")
        self.act = self.behave
        self.session: str | None = None

    def behave(self, request: AgentRequest) -> None:
        self.session = request.resume_session or f"sess-{len(self.requests)}"
        if request.on_session:
            request.on_session(self.session)
        if len(self.requests) == 2 and not request.resume_session:
            raise Killed("power loss")

    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request).model_copy(update={"session_id": self.session})
        if request.on_result is not None:
            request.on_result(result)
        return result


def agents(tmp_path: Path, *, build=None, review=None) -> dict:
    """The tick's agent callables over a faked `claude` for each."""
    build = build or FakeClaude(stdout=finished_build(tmp_path, "done"))
    review = review or FakeClaude(stdout=finished_build(tmp_path, approving()))
    return dict(
        run_claude=build_run_claude(runtime=ClaudeCodeRuntime(execute=build), model=BUILD_MODEL),
        run_review=build_run_review(runtime=ClaudeCodeRuntime(execute=review), model=REVIEW_MODEL),
    )


def ledger_lines(workspace: Installation) -> list[dict]:
    path = workspace.state_dir / "usage-ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def absent(record: dict, field: str) -> bool:
    return record.get(field) is None


def test_each_agent_call_of_the_unit_leaves_one_record_naming_where_it_was_made(
    tmp_path: Path, workspace: Installation
) -> None:
    outcome = tick(tmp_path, fresh(tmp_path), **agents(tmp_path))

    assert outcome.status == RunStatus.OPEN
    records = ledger_lines(workspace)
    assert Counter(r["node"] for r in records) == {"tests": 1, "implement": 1, "review": 1}
    assert all(r["kind"] == "agent" for r in records)
    assert {r["unit"] for r in records} == {"add-marker/1"}
    assert {r["change"] for r in records} == {unit().change}
    assert {r["repo"] for r in records} == {unit().repo}
    assert {r["tier"] for r in records} == {unit().tier}
    assert {r["runtime"] for r in records} == {"claude_code"}
    assert all(r["at"] for r in records)

    (review,) = [r for r in records if r["node"] == "review"]
    assert (review["round"], review["role"], review["model"]) == (1, "review", REVIEW_MODEL)
    (implement,) = [r for r in records if r["node"] == "implement"]
    assert (implement["round"], implement["role"], implement["model"]) == (
        0,
        "implement",
        BUILD_MODEL,
    )


def test_a_record_carries_what_the_runtime_reported_and_says_it_was_reported(
    tmp_path: Path, workspace: Installation
) -> None:
    tick(tmp_path, fresh(tmp_path), **agents(tmp_path))

    (review,) = [r for r in ledger_lines(workspace) if r["node"] == "review"]
    assert review["usage_source"] == "reported"
    assert review["input_tokens"] == 4
    assert review["output_tokens"] == 212
    assert review["cache_read_input_tokens"] == 14671
    assert review["cache_creation_input_tokens"] == 1822
    assert review["cost_usd"] == 0.4127
    assert review["turns"] == 3
    assert review["duration_ms"] == 81234
    assert review["session_id"] == SESSION


def test_a_failed_call_is_recorded_with_its_figures(
    tmp_path: Path, workspace: Installation
) -> None:
    *events, closing = finished_build(tmp_path, "done").splitlines()
    ended = json.loads(closing) | {
        "subtype": "error_max_turns",
        "is_error": True,
        "errors": ["reached the turn limit"],
    }
    del ended["result"]
    failing = FakeClaude(stdout="\n".join([*events, json.dumps(ended)]) + "\n", returncode=1)

    with contextlib.suppress(RuntimeError):
        tick(tmp_path, fresh(tmp_path), **agents(tmp_path, build=failing))

    (record,) = ledger_lines(workspace)
    assert record["node"] == "tests"
    assert record["usage_source"] == "reported"
    assert record["cost_usd"] == 0.4127
    assert record["outcome"] == "failed"


def test_a_run_that_exits_cleanly_on_an_error_result_is_recorded_as_failed(
    tmp_path: Path, workspace: Installation
) -> None:
    *events, closing = finished_build(tmp_path, "done").splitlines()
    ended = json.loads(closing) | {"subtype": "error_max_turns", "is_error": True}
    del ended["result"]
    capped = FakeClaude(stdout="\n".join([*events, json.dumps(ended)]) + "\n", returncode=0)

    with contextlib.suppress(RuntimeError):
        tick(tmp_path, fresh(tmp_path), **agents(tmp_path, build=capped))

    (record,) = [r for r in ledger_lines(workspace) if r["node"] == "tests"]
    assert record["usage_source"] == "reported"
    assert record["outcome"] == "failed"


def test_a_runtime_that_reports_nothing_leaves_a_record_of_none_with_the_figures_absent(
    tmp_path: Path, workspace: Installation
) -> None:
    runtime = Silent(answer="done")

    outcome = tick(
        tmp_path, fresh(tmp_path), run_claude=build_run_claude(runtime=runtime, model="m")
    )

    assert outcome.status == RunStatus.OPEN
    records = [r for r in ledger_lines(workspace) if r["node"] in ("tests", "implement")]
    assert len(records) == 2
    for record in records:
        assert record["usage_source"] == "none"
        assert record["runtime"] == "silent"
        for figure in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "cost_usd",
            "duration_ms",
        ):
            assert absent(record, figure), f"{figure} must be absent, not zero"


def test_a_ledger_that_cannot_be_written_leaves_the_run_unchanged_and_is_reported_once(
    tmp_path: Path, workspace: Installation
) -> None:
    # A file where the state directory should be: no append can succeed.
    workspace.state_dir.write_text("not a directory")
    recorder = fresh(tmp_path)

    outcome = tick(tmp_path, recorder, **agents(tmp_path))

    assert outcome.status == RunStatus.OPEN
    assert recorder.store.get("add-marker/1").state == "in_review"
    assert workspace.state_dir.read_text() == "not a directory"
    told = [line for line in recorder.logged if "ledger" in line.lower()]
    assert len(told) == 1, "three calls failed to record; the failure is reported once"


def test_a_node_killed_and_resumed_leaves_one_record_marked_resumed(
    tmp_path: Path, workspace: Installation
) -> None:
    runtime = KilledInImplement()
    recorder = fresh(tmp_path)
    run_claude = build_run_claude(runtime=runtime, model="m")
    with pytest.raises(Killed):
        tick(tmp_path, recorder, run_claude=run_claude)
    assert [r["node"] for r in ledger_lines(workspace)] == ["tests"], "a killed call writes none"

    tick(tmp_path, recorder, run_claude=run_claude)

    records = ledger_lines(workspace)
    (tests,) = [r for r in records if r["node"] == "tests"]
    assert tests["resumed"] is False
    (implement,) = [r for r in records if r["node"] == "implement"]
    assert implement["resumed"] is True
    assert implement["round"] == 0
    assert implement["session_id"] == "sess-2"
    read = read_ledger(workspace.state_dir / "usage-ledger.jsonl")
    assert [(r.round, r.session_id) for r in read if r.node == "implement"] == [(0, "sess-2")]
