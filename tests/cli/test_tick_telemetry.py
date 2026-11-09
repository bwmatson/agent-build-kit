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
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.events import Review
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.wiring import CommitRejected
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.conftest import make_installation
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
        project_limits={"max_concurrent_stacks": 2},
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
        cli, "build_fetch_review", lambda **_: lambda repo, pr: Review(lines=["rename the marker"])
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


def allow_once_then_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """The round admits the unit, then the window is spent: the guard the build
    meets agrees with the rounds after it, as a real one does."""
    answers = iter([Decision(may_start=True, reason="plenty")])
    monkeypatch.setattr(
        cli,
        "may_start_unit",
        lambda r: next(answers, Decision(may_start=False, reason="session usage at 88%")),
    )


# --- what is never attached ----------------------------------------------------------


# --- the metrics table -----------------------------------------------------------------


# --- the flush ---------------------------------------------------------------------------


def test_no_span_or_metric_carries_feedback_a_prompt_a_diff_or_a_commit_message(
    ticks: Ticks, exported: Collector
) -> None:
    feedback = "SENTINEL-comment: rename the lock in registry.py"
    ticks.recorder.verdicts = [rejecting(feedback)]
    ticks.recorder.unit_test_results = [(False, FAILING), (True, "")]
    ticks.answer = DIFF
    messages: list[str] = []
    real_commit = ticks.recorder.commit

    def commit(message: str, *, cwd: Path, base: str = "") -> int:
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
    def rejected(message: str, *, cwd: Path, base: str = "") -> int:
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


def test_a_failure_is_recorded_by_its_category_and_not_by_its_text(
    ticks: Ticks, exported: Collector
) -> None:
    ticks.recorder.unit_test_ok = False
    ticks.recorder.unit_test_output = "E   ImportError: SENTINEL-output cannot import 'geo'"
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


def test_a_tick_flushes_before_it_returns(ticks: Ticks, exported: Collector) -> None:
    ticks.agents()

    ticks.tick()

    # Read at once, with no shutdown by the test and long before a periodic
    # export of metrics would have run.
    assert "tick" in {span.name for span in exported.spans()}
    assert exported.metric("abk.tick.duration")
    assert exported.metric("abk.unit.duration")
