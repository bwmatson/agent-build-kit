"""An agent run ending on a network or provider outage parks its unit; any other failure fails it.

The runtime stand-in raises `NetworkUnavailable` from inside a step, as the adapters do, and
the probe is replaced at the seam the step handler reads it through. A strong sign parks on
its own evidence; a weak one parks only as the probe's two groups say; a probe that errors
never parks. A parked unit keeps everything the next run resumes from.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.graph.unit import Position, thread_position
from agent_build_kit.pipeline import network_probe
from agent_build_kit.pipeline.metric_records import InstrumentKind
from agent_build_kit.pipeline.network_probe import Reachability
from agent_build_kit.pipeline.unit_store import FeedbackSource, UnitStore
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, PLANNED, in_progress
from agent_build_kit.pipeline.wiring import INTERRUPTED_PROMPT
from agent_build_kit.runtimes import NetworkUnavailable
from tests.conftest import make_installation
from tests.factories import unit
from tests.leftovers_driver import Habitat, Hands, step_of
from tests.runner_fakes import Recorder, make_runner, rejecting

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = unit().id
API = "api.example.test"
WORDS = "API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)"


def outage(strength: str) -> NetworkUnavailable:
    return NetworkUnavailable(WORDS, strength=strength, host=API)  # type: ignore[arg-type]


class Probe:
    """The probe's answer, or the error it raises, and how often it was asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.answer: Reachability | Exception = Reachability(api=True, control=True)
        self.asked: list[str] = []
        self.ports: list[int] = []
        monkeypatch.setattr(network_probe, "probe_reachability", self)

    def __call__(self, api_host: str, *args: Any, **kwargs: Any) -> Reachability:
        self.asked.append(api_host)
        self.ports.append(kwargs.get("api_port", 443))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Probe:
    return Probe(monkeypatch)


def raises_in_implement(error: Exception, step: str = "implement"):
    """A run that fails with `error` when asked for `step` ("" for any), and otherwise answers."""

    def run(prompt: str, **kwargs: Any) -> str:
        if not step or step_of(prompt) == step:
            raise error
        return "done"

    return run


def build_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    store: UnitStore,
    *,
    recorder: Recorder | None = None,
    config: dict[str, Any] | None = None,
    **overrides: Any,
) -> Recorder:
    inst = make_installation(tmp_path, planning={"state_dir": "."}, **(config or {}))
    recorder = recorder or Recorder(store)
    runner = make_runner(store, recorder, tmp_path, **overrides)
    monkeypatch.setattr(cli, "build_runner", lambda u, **kw: runner)

    assert cli.build_unit(inst, store.get(UNIT), store=store) is True
    return recorder


def fresh_store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return store


def test_a_strong_sign_parks_the_unit_whatever_the_probe_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    store.set_feedback(UNIT, "rename the marker", source=FeedbackSource.REVIEW)

    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("strong"), "rework"))

    stored = store.get(UNIT)
    assert stored.state == PLANNED, "the work is fine; only the network is down"
    assert stored.cause == "network_unavailable"
    assert stored.step == "rework"
    assert "EAI_AGAIN" in stored.note
    assert stored.parked_attempts == 1
    assert probe.asked == [], "a name that did not resolve is evidence enough"
    assert stored.feedback == "rename the marker"
    assert stored.feedback_source == FeedbackSource.REVIEW
    assert stored.branch
    assert in_progress(stored), "a parked unit with a branch keeps its place"


def thread_state(tmp_path: Path) -> UnitRun:
    """The unit's thread as the checkpoint holds it, where the build left it."""

    async def read() -> Position:
        async with open_checkpointer(unit_graphs_path(tmp_path)) as saver:
            return await thread_position(saver, UNIT)

    position = asyncio.run(read())
    assert position.state is not None
    return position.state


@pytest.mark.parametrize(
    ("strength", "reached", "cause"),
    [
        ("strong", None, "network_unavailable"),
        ("weak", Reachability(api=False, control=True), "service_unavailable"),
    ],
)
def test_a_parked_unit_keeps_its_branch_thread_feedback_and_round_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe: Probe,
    capsys: pytest.CaptureFixture[str],
    strength: str,
    reached: Reachability | None,
    cause: str,
) -> None:
    """The outage comes on the second fix of the checks a rework broke, after one review round."""
    if reached is not None:
        probe.answer = reached
    outcomes: list[str] = []
    real_record = cli.emit_metric

    def record(
        instrument: InstrumentKind, name: str, value: float, log: Any, **labels: Any
    ) -> None:
        if name == "abk.unit.duration":
            outcomes.append(labels["outcome"])
        real_record(instrument, name, value, log, **labels)

    monkeypatch.setattr(cli, "emit_metric", record)
    store = fresh_store(tmp_path)
    recorder = Recorder(store)
    recorder.tier1_results = [
        (True, ""),
        (False, "E501 line too long"),
        (False, "E302 blank lines"),
    ]
    recorder.verdicts = [rejecting("rename it")]
    held: dict[str, Any] = {}

    def down(prompt: str, **kwargs: Any) -> str:
        if step_of(prompt) != "fix_checks" or "claude:fix_checks" not in recorder.events:
            return recorder.claude(prompt, **kwargs)
        now = store.get(UNIT)
        held.update(branch=now.branch, feedback=now.feedback, source=now.feedback_source)
        raise outage(strength)

    build_once(tmp_path, monkeypatch, store, recorder=recorder, run=down)

    parked = store.get(UNIT)
    assert (parked.state, parked.cause, parked.step) == (PLANNED, cause, "fix_checks")
    assert held["branch"], "a known branch"
    assert held["feedback"], "saved feedback"
    assert parked.branch == held["branch"]
    assert parked.feedback == held["feedback"]
    assert parked.feedback_source == held["source"]
    thread = thread_state(tmp_path)
    assert (thread.fix_rounds, thread.review_round, len(thread.review_rounds)) == (1, 1, 1)
    assert outcomes == ["interrupted"], "not recorded as a failed run"


@pytest.mark.parametrize(
    ("reached", "state", "cause"),
    [
        (Reachability(api=False, control=False), PLANNED, "network_unavailable"),
        (Reachability(api=False, control=True), PLANNED, "service_unavailable"),
        (Reachability(api=True, control=True), FAILED, "failed"),
        (Reachability(api=True, control=False), FAILED, "failed"),
        (RuntimeError("the probe broke"), FAILED, "failed"),
    ],
    ids=["both-down", "api-down-control-up", "api-up-control-up", "api-up", "probe-errors"],
)
def test_a_weak_sign_parks_the_unit_as_the_probe_sorts_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe: Probe,
    reached: Reachability | Exception,
    state: str,
    cause: str,
) -> None:
    probe.answer = reached
    store = fresh_store(tmp_path)

    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("weak")))

    stored = store.get(UNIT)
    assert (stored.state, stored.cause) == (state, cause)
    assert stored.step == "implement"
    assert "EAI_AGAIN" in stored.note
    assert probe.asked == [API]
    assert stored.parked_attempts == (0 if state == FAILED else 1)


def test_consecutive_parkings_count_whichever_of_the_three_causes_they_were(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    probe.answer = Reachability(api=False, control=True)
    store = fresh_store(tmp_path)
    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("strong"), ""))
    assert store.get(UNIT).cause == "network_unavailable"
    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("weak"), ""))
    assert store.get(UNIT).cause == "service_unavailable"

    def host_down(prompt: str, **kwargs: Any) -> str:
        raise HostUnavailable("create_pr", "HTTP 500", 3)

    build_once(tmp_path, monkeypatch, store, run=host_down)

    stored = store.get(UNIT)
    assert stored.cause == "host_unavailable"
    assert stored.parked_attempts == 3


def test_a_parked_unit_resumes_at_its_step_and_starts_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    habitat = Habitat(tmp_path, Hands(die_in="implement", dies=outage("strong"), sessions=False))
    store = fresh_store(tmp_path)
    build_once(tmp_path, monkeypatch, store, **habitat.overrides())
    assert store.get(UNIT).cause == "network_unavailable"

    build_once(tmp_path, monkeypatch, store, **habitat.overrides())

    again = habitat.runtime.after_death()[0]
    assert step_of(again.prompt) == "implement"
    assert not again.resume_session
    assert store.get(UNIT).state == IN_REVIEW
    assert store.get(UNIT).parked_attempts == 0


def test_a_step_that_was_continuing_a_session_continues_it_after_a_parking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    habitat = Habitat(tmp_path, Hands(die_in="rework", dies=outage("strong")))
    store = fresh_store(tmp_path)
    # The reviewer sends the unit back once; the rework step is where the network goes.
    recorder = Recorder(store)
    recorder.verdicts = [rejecting("rename it")]
    build_once(tmp_path, monkeypatch, store, recorder=recorder, **habitat.overrides())
    parked = store.get(UNIT)
    assert (parked.state, parked.cause, parked.step) == (PLANNED, "network_unavailable", "rework")

    build_once(tmp_path, monkeypatch, store, recorder=recorder, **habitat.overrides())

    resumed = habitat.runtime.after_death()[0]
    assert resumed.resume_session, "the session it was continuing is continued"
    assert resumed.prompt == INTERRUPTED_PROMPT
    assert store.get(UNIT).state == IN_REVIEW


def test_the_probe_is_asked_about_the_port_the_run_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    probe.answer = Reachability(api=True, control=True)
    gateway_port = (
        8443  # a name, not a literal: the timing guard reads `port=<number>` as a bound port
    )
    called = NetworkUnavailable(
        WORDS, strength="weak", host="gateway.example.test", port=gateway_port
    )

    build_once(tmp_path, monkeypatch, fresh_store(tmp_path), run=raises_in_implement(called))

    assert (probe.asked, probe.ports) == (["gateway.example.test"], [8443])
