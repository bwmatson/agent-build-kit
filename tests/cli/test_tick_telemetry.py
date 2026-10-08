"""What a tick sends when telemetry is on: the spans of its units' runs and the
metrics of the pipeline's time, rounds and outcomes (spec: telemetry).

A tick runs through `cmd_tick` over the graph engine, with the runner's
callables faked. An agent call goes through the real Claude Code adapter, with
the `claude` process faked at its boundary, so the spans an agent run makes are
the adapter's own. What is sent is read back from an in-process OTLP/HTTP
receiver; no test shuts telemetry down itself, since flushing before it returns
is the tick's job.
"""

from __future__ import annotations

import argparse
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import Review
from agent_build_kit.pipeline.units import PLANNED, RUNNING, branch_name
from agent_build_kit.pipeline.usage_guard import Decision, RateLimited
from agent_build_kit.pipeline.wiring import CommitRejected
from agent_build_kit.pipeline.workspaces import branch_lock
from agent_build_kit.runtimes import AgentRequest, claude_code
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.conftest import make_installation
from tests.factories import unit
from tests.graph_driver import fresh
from tests.otlp import Collector, Point, Span, enabled
from tests.runner_fakes import Recorder, make_runner, rejecting
from tests.runtimes.claude_cli import MODEL, FakeClaude, finished_build

UNIT = "add-marker/1"
OTHER = "other/1"
FAILING = (
    "$ uv run pre-commit run --from-ref main --to-ref HEAD (exit 1)\n"
    "ruff format..............................................................Passed\n"
    "ruff check...............................................................Passed\n"
    "pyrefly check............................................................Failed\n"
    "- hook id: pyrefly-check\n"
    "- exit code: 1\n"
    "\n"
    "ERROR implicit-any-empty-container\n  --> tests/test_x.py:3:5"
)
ERROR = 2  # an OTLP span status code
DIFF = 'diff --git a/src/app.py b/src/app.py\n-MARKER = None\n+MARKER = "added"'
SPEC_STEPS = {"tests", "implement", "checks", "review", "rework", "push", "open_pr"}


class Ticks:
    def __init__(self, inst: Installation, recorder: Recorder, options: dict[str, Any]) -> None:
        self.inst, self.recorder, self.options = inst, recorder, options
        self.store = recorder.store
        self.answer = "done"

    def tick(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False, only=None), self.inst)

    def agents(self) -> None:
        """Have each agent call of the build run through the Claude Code adapter."""

        def through_adapter(role: str, inner: Callable[..., Any]) -> Callable[..., Any]:
            def run(*args: Any, **kwargs: Any) -> Any:
                result = inner(*args, **kwargs)
                prompt = kwargs.get("context") or (args[0] if args else "")
                fake = FakeClaude(stdout=finished_build(kwargs["cwd"], self.answer))
                ClaudeCodeRuntime(execute=fake).run(
                    AgentRequest(prompt=prompt, role=role, cwd=kwargs["cwd"], model=MODEL)  # pyrefly: ignore
                )
                return result

            return run

        claude, review = self.recorder.claude, self.recorder.review
        self.options.update(
            run=through_adapter("implement", claude),
            run_review=through_adapter("review", review),
            run_rework_review=through_adapter("rework_review", review),
        )


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        yield collector


@pytest.fixture
def ticks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exported: Collector) -> Ticks:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 2},
    )
    recorder = fresh(tmp_path)
    options: dict[str, Any] = {}

    def runner(u: Any, **kwargs: Any) -> Any:
        return make_runner(recorder.store, recorder, tmp_path, **options)

    monkeypatch.setattr(cli, "build_runner", runner)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))
    monkeypatch.setattr(
        cli, "build_fetch_review", lambda: lambda repo, pr: Review(lines=["rename the marker"])
    )
    monkeypatch.setattr(cli, "build_restack", lambda **kw: lambda **a: None)
    monkeypatch.setattr(cli, "build_retarget", lambda: lambda unit, base: None)
    return Ticks(inst, recorder, options)


def one(spans: list[Span], name: str) -> Span:
    found = [span for span in spans if span.name == name]
    assert len(found) == 1, f"expected one {name!r} span, got {[s.name for s in spans]}"
    return found[0]


def steps(spans: list[Span]) -> list[Span]:
    return [span for span in spans if "step" in span.attributes]


def below(spans: list[Span], parent: Span) -> list[Span]:
    return [span for span in spans if span.parent_id == parent.span_id]


def texts(spans: list[Span], points: list[Point]) -> list[str]:
    values = [text for span in spans for text in span.texts()]
    for point in points:
        values += [v for v in point.attributes.values() if isinstance(v, str)]
    return values


# --- the shape of a run -----------------------------------------------------------


def test_a_unit_reviewed_twice_is_traced_from_the_tick_to_each_agent_call(
    ticks: Ticks, exported: Collector
) -> None:
    ticks.recorder.verdicts = [rejecting("rename the lock")]
    ticks.agents()

    assert ticks.tick() == 0

    spans = exported.spans()
    tick = one(spans, "tick")
    run = one(spans, "unit")
    assert run.parent_id == tick.span_id
    assert {span.trace_id for span in spans} == {tick.trace_id}
    assert run.attributes["unit.id"] == UNIT
    assert run.attributes["change"] == "add-marker"
    assert run.attributes["repo"] == "app"
    assert run.attributes["tier"] == "tier1"
    assert run.attributes["outcome"] == "open"

    in_run = steps(spans)
    assert {span.parent_id for span in in_run} == {run.span_id}
    assert SPEC_STEPS <= {span.attributes["step"] for span in in_run}
    reviews = [span for span in in_run if span.attributes["step"] == "review"]
    assert [span.attributes["round"] for span in reviews] == [1, 2]
    for review in reviews:
        agents = below(spans, review)
        assert [agent.name for agent in agents] == ["agent"]
        assert agents[0].attributes["role"] == "review"
    rework = next(span for span in in_run if span.attributes["step"] == "rework")
    assert [agent.attributes["role"] for agent in below(spans, rework)] == ["implement"]

    agents = [span for span in spans if span.name == "agent"]
    assert agents, "no agent span"
    for agent in agents:
        assert agent.parent_id in {span.span_id for span in in_run}
        assert agent.attributes["runtime"] == claude_code.RUNTIME.name
        assert agent.attributes["model"] == MODEL
        assert agent.attributes["turns"] == 3
        assert agent.attributes["outcome"] == "ok"


def test_the_units_of_a_tick_built_in_parallel_threads_share_the_ticks_trace(
    ticks: Ticks, exported: Collector
) -> None:
    ticks.store.upsert([unit(OTHER, change="other")])
    ticks.agents()
    both = threading.Barrier(2, timeout=30)
    waited: set[str] = set()
    implement = ticks.options["run"]

    def meet(*args: Any, **kwargs: Any) -> Any:
        # Each unit's first agent call waits for the other's: they run at once.
        if threading.current_thread().name not in waited:
            waited.add(threading.current_thread().name)
            both.wait()
        return implement(*args, **kwargs)

    ticks.options["run"] = meet

    assert ticks.tick() == 0

    spans = exported.spans()
    tick = one(spans, "tick")
    runs = [span for span in spans if span.name == "unit"]
    assert {span.attributes["unit.id"] for span in runs} == {UNIT, OTHER}
    assert {span.parent_id for span in runs} == {tick.span_id}
    assert {span.trace_id for span in spans} == {tick.trace_id}
    own = {run.span_id: [s for s in below(spans, run) if "step" in s.attributes] for run in runs}
    assert all(own.values()), "each unit's steps sit below its own span"


def test_a_unit_resumed_in_a_later_tick_links_to_its_earlier_trace(
    ticks: Ticks, exported: Collector
) -> None:
    ticks.agents()
    ticks.options["may_start"] = lambda: (False, "session usage at 88%")
    ticks.options["resume_at"] = lambda: datetime.now(UTC) + timedelta(hours=1)
    ticks.tick()
    earlier = one(exported.spans(), "unit")
    assert ticks.store.get(UNIT).state == RUNNING

    ticks.options["may_start"] = lambda: (True, "usage fine")
    ticks.tick()

    later = [
        span for span in exported.spans() if span.name == "unit" and span.span_id != earlier.span_id
    ]
    resumed = next(span for span in later if span.trace_id != earlier.trace_id)
    assert resumed.attributes["unit.id"] == UNIT
    assert earlier.trace_id in resumed.links
    assert earlier.links == (), "the first run has nothing to link to"


def test_a_tick_that_skips_a_unit_leaves_the_trace_of_the_run_that_built_it(
    ticks: Ticks, exported: Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks.agents()
    ticks.options["may_start"] = lambda: (False, "session usage at 88%")
    ticks.options["resume_at"] = lambda: datetime.now(UTC) + timedelta(hours=1)
    ticks.tick()
    first = one(exported.spans(), "unit")
    built = ticks.store.get(UNIT).trace
    assert built.startswith(first.trace_id)
    ticks.options["may_start"] = lambda: (True, "usage fine")
    # The pass's evaluation lags the store: it offers a unit another tick holds.
    evaluated = cli.ready_units
    stale = [True]
    monkeypatch.setattr(
        cli,
        "ready_units",
        lambda graph, **kw: (
            [u for u in graph if u.id == UNIT] if stale[0] else evaluated(graph, **kw)
        ),
    )

    with branch_lock(branch_name(ticks.store.get(UNIT)), root=ticks.inst.state_dir / "locks"):
        ticks.tick()

    skipped = [s for s in exported.spans() if s.name == "unit" and s.span_id != first.span_id]
    assert [s.attributes["outcome"] for s in skipped] == ["skipped"]
    assert ticks.store.get(UNIT).trace == built

    stale[0] = False
    ticks.tick()

    last = [
        s
        for s in exported.spans()
        if s.name == "unit" and s.span_id not in {first.span_id, skipped[0].span_id}
    ]
    assert len(last) == 1
    assert first.trace_id in last[0].links
    assert skipped[0].trace_id not in last[0].links


# --- what is never attached ----------------------------------------------------------


def test_no_span_or_metric_carries_feedback_a_prompt_a_diff_or_a_commit_message(
    ticks: Ticks, exported: Collector
) -> None:
    feedback = "SENTINEL-comment: rename the lock in registry.py"
    ticks.recorder.verdicts = [rejecting(feedback)]
    ticks.recorder.tier1_results = [(False, FAILING), (True, "")]
    ticks.answer = DIFF
    messages: list[str] = []
    real_commit = ticks.recorder.commit

    def commit(message: str, *, cwd: Path) -> int:
        messages.append(message)
        return real_commit(message, cwd=cwd)

    ticks.options["commit"] = commit
    ticks.agents()

    ticks.tick()

    spans, points = exported.spans(), exported.points()
    assert spans and points
    assert any("SENTINEL" in prompt for prompt in ticks.recorder.prompts), "the comment was used"
    secrets = [feedback, DIFF, FAILING, *ticks.recorder.prompts, *ticks.recorder.contexts]
    secrets += messages
    values = texts(spans, points)
    for secret in secrets:
        assert not [value for value in values if secret in value], secret
    assert not [value for value in values if "SENTINEL" in value or "MARKER" in value]


def test_a_commit_the_gate_rejects_leaves_its_text_on_no_span(
    ticks: Ticks, exported: Collector
) -> None:
    def rejected(message: str, *, cwd: Path) -> int:
        raise CommitRejected("git commit was rejected: SENTINEL-gate said\n" + DIFF)

    ticks.options["commit"] = rejected
    ticks.agents()

    ticks.tick()

    spans = exported.spans()
    assert spans
    assert not [value for span in spans for value in span.texts() if "SENTINEL" in value]
    assert not [span for span in spans if span.events], "no exception event on any span"
    failed = [span for span in steps(spans) if span.status_code == ERROR]
    assert failed, "the step the rejection passed through is marked as an error"
    assert all(span.status_message == "" for span in failed)


def test_a_step_that_waits_for_review_is_not_an_error(ticks: Ticks, exported: Collector) -> None:
    ticks.agents()

    ticks.tick()

    spans = exported.spans()
    waiting = one(spans, "await_review")
    assert waiting.events == ()
    assert waiting.status_code == 0
    assert waiting.attributes["outcome"] == "waiting"
    assert not [span for span in spans if span.status_code == ERROR]


def test_a_failure_is_recorded_by_its_category_and_not_by_its_text(
    ticks: Ticks, exported: Collector
) -> None:
    ticks.recorder.tier1_ok = False
    ticks.recorder.tier1_output = "E   ImportError: SENTINEL-output cannot import 'geo'"
    ticks.agents()

    ticks.tick()

    spans, points = exported.spans(), exported.points()
    assert one(spans, "unit").attributes["outcome"] == "failed"
    assert not [value for value in texts(spans, points) if "SENTINEL" in value or "geo" in value]


def test_unit_ids_and_change_names_are_on_spans_and_on_no_metric(
    ticks: Ticks, exported: Collector
) -> None:
    ticks.agents()

    ticks.tick()

    spans, points = exported.spans(), exported.points()
    on_spans = [value for span in spans for value in span.attributes.values()]
    assert UNIT in on_spans and "add-marker" in on_spans
    assert points
    for point in points:
        assert not {"unit", "unit.id", "change"} & set(point.attributes), point.metric
        assert (
            UNIT not in point.attributes.values() and "add-marker" not in point.attributes.values()
        )


# --- the metrics table -----------------------------------------------------------------


def test_a_unit_built_reviewed_twice_and_pushed_records_the_tables_instruments(
    ticks: Ticks, exported: Collector
) -> None:
    ticks.recorder.verdicts = [rejecting("rename the lock")]
    ticks.recorder.tier1_results = [(False, FAILING), (True, "")]
    ticks.agents()

    assert ticks.tick() == 0

    def attributes(name: str) -> list[set[str]]:
        return [set(point.attributes) for point in exported.metric(name)]

    assert attributes("abk.tick.duration") == [{"outcome"}]
    assert attributes("abk.unit.duration") == [{"repo", "tier", "outcome"}]
    unit_duration = exported.metric("abk.unit.duration")[0]
    assert unit_duration.attributes == {"repo": "app", "tier": "tier1", "outcome": "open"}

    step_duration = exported.metric("abk.step.duration")
    assert {set(point.attributes) == {"step", "outcome"} for point in step_duration} == {True}
    assert SPEC_STEPS <= {point.attributes["step"] for point in step_duration}

    (rounds,) = exported.metric("abk.review.rounds")
    assert rounds.attributes == {"repo": "app", "outcome": "open"}
    assert (rounds.count, rounds.value) == (1, 2), "one unit, two rounds"

    failures = exported.metric("abk.checks.failures")
    assert failures and all(set(point.attributes) == {"check", "round"} for point in failures)
    assert {point.attributes["check"] for point in failures} == {"types"}

    turns = exported.metric("abk.agent.turns")
    assert turns and all(set(point.attributes) == {"role", "model"} for point in turns)
    assert {point.attributes["model"] for point in turns} == {MODEL}
    assert {"implement", "review"} <= {point.attributes["role"] for point in turns}

    tokens = exported.metric("abk.agent.tokens")
    assert all(set(point.attributes) == {"role", "model", "kind"} for point in tokens)
    assert {point.attributes["kind"] for point in tokens} == {"input", "output", "cache"}

    states = {point.attributes["state"] for point in exported.metric("abk.units")}
    assert states and states <= {"planned", "running", "in_review", "held", "failed"}
    assert not exported.metric("abk.usage.pauses")
    assert not exported.metric("abk.units.reclaimed")


def test_a_tick_paused_for_the_usage_window_counts_a_pause_with_its_kind(
    ticks: Ticks, exported: Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    resume = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr(
        cli,
        "may_start_unit",
        lambda r: Decision(may_start=False, reason="session usage at 90%", resume_at=resume),
    )

    assert ticks.tick() == 0

    (paused,) = exported.metric("abk.usage.pauses")
    assert paused.attributes == {"kind": "usage"}
    assert paused.value == 1
    assert ticks.recorder.events == [], "nothing was built"


def test_a_run_refused_by_the_agents_rate_limit_counts_a_rate_limit_pause(
    ticks: Ticks, exported: Collector
) -> None:
    def refused(*args: Any, **kwargs: Any) -> str:
        raise RateLimited("usage limit reached", resets_at=datetime.now(UTC) + timedelta(hours=2))

    ticks.options["run"] = refused

    ticks.tick()

    assert [p.attributes for p in exported.metric("abk.usage.pauses")] == [{"kind": "rate_limit"}]


def test_a_step_refused_by_the_agents_rate_limit_is_not_an_error(
    ticks: Ticks, exported: Collector
) -> None:
    calls: list[str] = []
    claude = ticks.recorder.claude

    def refused(*args: Any, **kwargs: Any) -> str:
        # The tests agent goes through; the implement agent is refused.
        calls.append("agent")
        if len(calls) == 1:
            return claude(*args, **kwargs)
        raise RateLimited("usage limit reached", resets_at=datetime.now(UTC) + timedelta(hours=2))

    ticks.options["run"] = refused

    ticks.tick()

    implement = next(s for s in steps(exported.spans()) if s.attributes["step"] == "implement")
    assert implement.status_code == 0
    assert implement.attributes["outcome"] == "rate_limited"
    (point,) = [
        p for p in exported.metric("abk.step.duration") if p.attributes["step"] == "implement"
    ]
    assert point.attributes["outcome"] == "rate_limited"


def test_a_unit_no_run_holds_is_counted_when_the_tick_reclaims_it(
    ticks: Ticks, exported: Collector, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks.store.set_state(UNIT, RUNNING, note="killed before a thread")
    monkeypatch.setattr(
        cli,
        "may_start_unit",
        lambda r: Decision(
            may_start=False, reason="usage", resume_at=datetime.now(UTC) + timedelta(hours=1)
        ),
    )

    ticks.tick()

    assert ticks.store.get(UNIT).state == PLANNED
    (reclaimed,) = exported.metric("abk.units.reclaimed")
    assert reclaimed.value == 1
    assert reclaimed.attributes == {}


# --- the flush ---------------------------------------------------------------------------


def test_a_tick_flushes_before_it_returns(ticks: Ticks, exported: Collector) -> None:
    ticks.agents()

    ticks.tick()

    # Read at once, with no shutdown by the test and long before a periodic
    # export of metrics would have run.
    assert "tick" in {span.name for span in exported.spans()}
    assert exported.metric("abk.tick.duration")
    assert exported.metric("abk.unit.duration")
