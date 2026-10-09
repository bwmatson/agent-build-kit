"""Running one unit's build path through its thread."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.constants import START
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot

from agent_build_kit import telemetry
from agent_build_kit.graph.build import BUILD_NODES, compile_build_path
from agent_build_kit.graph.nodes import WAITS, BuildPath
from agent_build_kit.graph.run import run_thread
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent, UnitRun
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.metric_records import record_metric
from agent_build_kit.pipeline.run_log import RunLog
from agent_build_kit.pipeline.stack_runner import PauseInfo, RunOutcome, RunStatus, UnitRunner
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, feedback_source_of
from agent_build_kit.pipeline.units import FAILED, HELD, Unit, branch_name
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_lock


class Tracer(Protocol):
    """The part of an OpenTelemetry tracer a node's span uses."""

    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: Mapping[str, str | int] | None = None,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ) -> AbstractContextManager[object]: ...


class NotWaiting(RuntimeError):
    """An event for a unit whose thread is not in a wait, and cannot be put in one."""


class Position(Frozen):
    """Where a unit's thread stands: the nodes still to run (empty when it has
    ended or does not exist), its state, and the usage pause it waits in."""

    next: tuple[Node, ...] = ()
    state: UnitRun | None = None
    pause: PauseInfo | None = None
    paused_since: datetime | None = None


async def _nothing(state: UnitRun) -> dict[str, Any]:
    return {}


def _position(snapshot: StateSnapshot) -> Position:
    pause = None
    since = None
    for task in snapshot.tasks:
        for waiting in task.interrupts:
            value = waiting.value
            if isinstance(value, dict) and "reason" in value:
                until, began = value.get("until"), value.get("at")
                pause = PauseInfo(
                    reason=value["reason"], until=datetime.fromisoformat(until) if until else None
                )
                since = datetime.fromisoformat(began) if began else None
    return Position(
        next=tuple(Node(name) for name in snapshot.next),
        state=UnitRun.model_validate(snapshot.values) if snapshot.values else None,
        pause=pause,
        paused_since=since,
    )


def _compiled(saver: BaseCheckpointSaver, path: BuildPath | None = None) -> CompiledStateGraph:
    work = path.work() if path else {node: _nothing for node in BUILD_NODES}
    return compile_build_path(saver, work)


def _config(unit_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": unit_id}}


async def thread_position(saver: BaseCheckpointSaver, unit_id: str) -> Position:
    """Read `unit_id`'s thread without running it."""
    return _position(await _compiled(saver).aget_state(_config(unit_id)))


async def clear_running_node(saver: BaseCheckpointSaver, unit_id: str) -> None:
    """Forget the start a killed node left in `unit_id`'s thread, leaving the thread where it
    is. A person has taken over the files that run left, so no later run is to take them for
    its own."""
    compiled = _compiled(saver)
    where = _position(await compiled.aget_state(_config(unit_id)))
    if where.state is None or not where.state.running_node:
        return
    await compiled.aupdate_state(_config(unit_id), {"running_node": ""})


async def set_pending_replies(
    saver: BaseCheckpointSaver, unit_id: str, replies: tuple[str, ...]
) -> None:
    """Replace the replies a unit's thread still owes its pull request, leaving it waiting
    for review where it is. A thread that is not waiting there is not touched: its own run
    holds those replies."""
    compiled = _compiled(saver)
    where = _position(await compiled.aget_state(_config(unit_id)))
    if tuple(where.next) != (Node.AWAIT_REVIEW,):
        return
    # `open_pr` is the node that sends a thread to wait for review, so writing as it keeps
    # the thread's next step the same; without a node the update is ambiguous.
    await compiled.aupdate_state(
        _config(unit_id), {"pending_replies": replies}, as_node=Node.OPEN_PR.value
    )


async def seed_thread(
    saver: BaseCheckpointSaver, state: UnitRun, *, as_node: Node | None = None
) -> None:
    """Make a thread for `state`, positioned as if `as_node` had just finished
    (before the first node when None), so the node its router names runs next."""
    compiled = _compiled(saver)
    await compiled.aupdate_state(
        _config(state.unit_id),
        state.model_dump(),
        as_node=as_node.value if as_node else START,
    )


def _record_sessions(path: BuildPath, compiled: CompiledStateGraph, unit_id: str) -> None:
    """Have the agent's session id written into the thread's state as soon as
    the runtime reports it, which is what lets a node killed mid-agent resume it."""
    loop = asyncio.get_running_loop()

    def record(session: str) -> None:
        # Called on the thread a node runs on, while the loop is free.
        asyncio.run_coroutine_threadsafe(
            compiled.aupdate_state(_config(unit_id), {"session_id": session}), loop
        ).result()

    def start(node: str) -> None:
        asyncio.run_coroutine_threadsafe(
            compiled.aupdate_state(_config(unit_id), {"running_node": node}), loop
        ).result()

    path.on_session = record
    path.on_start = start


async def _outcome(compiled: CompiledStateGraph, unit_id: str) -> RunOutcome:
    """How the run `compiled` just made ended: paused for usage, or as its state says."""
    where = _position(await compiled.aget_state(_config(unit_id)))
    state = where.state
    if where.pause:
        return RunOutcome(
            status=RunStatus.PAUSED,
            detail=where.pause.reason,
            pr=state.pr if state else None,
            pause=where.pause,
        )
    if state is None or state.status is None:
        raise RuntimeError(f"the thread for {unit_id} ended without a status")
    return RunOutcome(status=state.status, detail=state.detail, pr=state.pr)


async def resume_unit(
    runner: UnitRunner,
    unit: Unit,
    *,
    base: str,
    graph: list[StoredUnit],
    saver: BaseCheckpointSaver,
    event: ResumeEvent,
    locks: Path,
    feedback: Callable[[], tuple[str, bool, tuple[str, ...]]] | None = None,
    run_log: RunLog | None = None,
    tracer: Tracer | None = None,
) -> RunOutcome:
    """Deliver `event` to the unit's thread as a resume command, and stop.

    Only the wait node's `on_event` runs: the store writes and the event in the
    state. The thread is left positioned at the node the event routes to (a
    `rework` goes to `rework`, a moved base or a requeue to `prepare`) with the
    unit `running`, so the tick runs it in a slot like any thread with work to
    do. Nothing here runs an agent, a check or a push.

    The unit's branch lock is held from the first read of the thread until the
    delivery returns: a node another loop or process is running shows the same
    `next` as one that was cut short. While the lock is held elsewhere this
    raises `BranchBusy`, with the thread untouched. A thread that has a node to
    run, cut short, paused or already routed by an earlier event, is not carried
    on here either: the event is refused with `BranchBusy`, for the caller to
    keep and deliver again once the tick has run the thread to a wait.

    `feedback`, when given, supplies the event's feedback, whether it is a
    person's words, and the ids of the comments it was built from, and is called only
    once the lock is held and the thread is waiting to take it: a delivery refused
    fetches nothing."""
    path = BuildPath(runner, unit, base=base, graph=graph, run_log=run_log, tracer=tracer)
    compiled = _compiled(saver, path)
    with branch_lock(branch_name(unit), root=locks):
        return await _deliver(path, compiled, unit, saver, event, feedback)


async def _deliver(
    path: BuildPath,
    compiled: CompiledStateGraph,
    unit: Unit,
    saver: BaseCheckpointSaver,
    event: ResumeEvent,
    feedback: Callable[[], tuple[str, bool, tuple[str, ...]]] | None = None,
) -> RunOutcome:
    where = _position(await compiled.aget_state(_config(unit.id)))
    ended = where.state
    if ended is None:
        raise LookupError(f"{unit.id} has no thread to deliver {event.kind.value} to")
    waiting = bool(set(where.next) & WAITS)
    over = event.kind in (EventKind.MERGED, EventKind.CLOSED)
    if over and not waiting:
        # Nothing waiting to route it: the unit is over either way.
        await saver.adelete_thread(unit.id)
        return RunOutcome(status=ended.status or RunStatus.OPEN, detail=event.kind.value)
    if where.next and not waiting and await _stopped_by_error(path, unit):
        # A node raised and the caller recorded the unit failed or held, so the
        # thread still shows that node to run though nothing will run it. It is
        # an ended thread: put it where one is, and deliver as to one.
        await compiled.aupdate_state(_config(unit.id), {}, as_node=Node.FAILED.value)
        where = _position(await compiled.aget_state(_config(unit.id)))
    if where.next and not waiting:
        names = ", ".join(node.value for node in where.next)
        raise BranchBusy(f"{unit.id} has {names} to run; {event.kind.value} is kept for later")
    if waiting:
        if feedback is not None:
            words, from_person, ids = await asyncio.to_thread(feedback)
            event = event.model_copy(
                update={
                    "feedback": words,
                    "from_person": from_person,
                    "comment_ids": ids,
                    "feedback_source": feedback_source_of(event.rework),
                }
            )
        command = Command(resume=event.model_dump(mode="json"))
        await run_thread(compiled, command, unit.id, interrupt_after=list(WAITS))
    elif event.kind in (EventKind.REQUEUE, EventKind.ADOPTED):
        # An ended thread, `failed`: what a requeue of a held unit does, from the same place.
        update = await asyncio.to_thread(path.on_event, ended, event)
        await compiled.aupdate_state(_config(unit.id), update, as_node=Node.HELD.value)
    else:
        raise NotWaiting(f"{unit.id} is not waiting: {event.kind.value} was not delivered")
    where = _position(await compiled.aget_state(_config(unit.id)))
    if over:
        await saver.adelete_thread(unit.id)
    state = where.state
    if state is None:
        raise RuntimeError(f"the thread for {unit.id} lost its state delivering {event.kind.value}")
    ahead = ", ".join(node.value for node in where.next) or "nothing"
    return RunOutcome(
        status=state.status or RunStatus.OPEN,
        detail=state.detail or f"{event.kind.value} delivered; {ahead} runs next",
        pr=state.pr,
    )


async def _stopped_by_error(path: BuildPath, unit: Unit) -> bool:
    """Whether the store says `unit` is no longer running: a run that raised
    left its thread at the node that did. The caller holds the branch lock, so
    no run of this unit is behind a pending node."""
    stored = await asyncio.to_thread(path.runner.store.get, unit.id)
    if stored.state in (FAILED, HELD):
        return True
    # Requeued while a merge gate was unmet: `planned`, its thread left where
    # the error stopped it, the requeue waiting to be delivered.
    return stored.cause is Cause.GATED and stored.gated_requeue is not None


async def run_unit(
    runner: UnitRunner,
    unit: Unit,
    *,
    base: str,
    graph: list[StoredUnit],
    saver: BaseCheckpointSaver,
    run_log: RunLog | None = None,
    tracer: Tracer | None = None,
) -> RunOutcome:
    """Start the unit's thread, or resume it where a killed or paused run left
    it, over the callables `runner` carries, and return what `UnitRunner.run`
    would.

    The caller holds the unit's branch lock for the whole run, as the tick
    does; the nodes do not take it."""
    path = BuildPath(runner, unit, base=base, graph=graph, run_log=run_log, tracer=tracer)
    compiled = _compiled(saver, path)
    _record_sessions(path, compiled, unit.id)
    where = _position(await compiled.aget_state(_config(unit.id)))
    if where.paused_since:
        path.paused_since = spans.Mark(where.paused_since)
    # A thread with a node still to run was interrupted: it carries on from
    # there, with no new input. One waiting for review or a person, or
    # ended, takes a new run of the unit.
    interrupted = bool(where.next) and not set(where.next) & WAITS
    # The whole state, not the fields set: a pydantic input writes only
    # those, and the previous run's verdict, pr and event would carry over.
    start = (
        None
        if interrupted
        else UnitRun(unit_id=unit.id, change=unit.change, groups=unit.groups).model_dump()
    )
    await run_thread(compiled, start, unit.id)
    outcome = await _outcome(compiled, unit.id)
    if outcome.status != RunStatus.PAUSED:
        # A paused run has more rounds to come; this is the count of one that ended.
        ended = _position(await compiled.aget_state(_config(unit.id))).state
        telemetry.observe(
            "abk.review.rounds",
            ended.review_round if ended else 0,
            repo=unit.repo,
            outcome=str(outcome.status),
        )
        record_metric(
            "abk.review.rounds",
            ended.review_round if ended else 0,
            runner.log,
            unit=unit.id,
            change=unit.change,
            repo=unit.repo,
            outcome=str(outcome.status),
        )
    if outcome.status == RunStatus.SATISFIED:
        # A thread lasts until the unit merges, is closed or is satisfied.
        await saver.adelete_thread(unit.id)
        # Now the run has left its tree: removing it earlier would pull the
        # floor from under the node that found the unit satisfied.
        runner.remove_satisfied(unit)
    return outcome
