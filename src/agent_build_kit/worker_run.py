"""The worker's runs: building, resolving and verifying one unit."""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import (
    Callable,
)
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

from agent_build_kit import (
    claude_account,
    config,
    orchestration,
    runtimes,
    telemetry,
)
from agent_build_kit.budget import cut_head
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.graph.state import Node, UnitRun
from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.artifacts import INTERFACE as ARTIFACTS
from agent_build_kit.pipeline import (
    code_host,
    spans,
)
from agent_build_kit.pipeline.e2e import (
    LOCK_WAIT_SETTING,
    stack_lock,
)
from agent_build_kit.pipeline.git_output import PUSH_OPERATION
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.metric_records import emit_metric
from agent_build_kit.pipeline.pause import (
    network_marker,
    pause_line,
    pause_until,
)
from agent_build_kit.pipeline.resolution_lane import (
    Lane,
    Rest,
    about_the_move,
    base_tip,
    forget_run_attempt,
    hold_if_spent,
    in_a_lane_run,
    record_run_attempt,
)
from agent_build_kit.pipeline.restack import (
    Moved,
    TemporaryTree,
)
from agent_build_kit.pipeline.run_log import (
    RunLog,
)
from agent_build_kit.pipeline.stack_runner import (
    PauseInfo,
    RunOutcome,
    UnitOutcome,
    UnitRunner,
)
from agent_build_kit.pipeline.unit_store import (
    PARK_BACKOFF,
    PARKED_CAUSES,
    Cause,
    HeldBy,
    StoredUnit,
    UnitStore,
)
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    PLANNED,
    RUNNING,
    Unit,
    UnitState,
    base_of,
    branch_name,
    local_ref,
)
from agent_build_kit.pipeline.usage_guard import (
    Interrupted,
    RateLimited,
    held_usage,
)
from agent_build_kit.pipeline.verify import SplitHeld, Verification, VerifyRecord, verify_change
from agent_build_kit.pipeline.wiring import (
    build_resume_at,
    moving_onto,
    own_work_starts_after,
)
from agent_build_kit.pipeline.workspaces import (
    BranchBusy,
    branch_lock,
    checked_out_elsewhere,
    unit_tree,
)
from agent_build_kit.profiles.base import ProfileUnsupported
from agent_build_kit.redaction import redact_text
from agent_build_kit.runtimes import AgentRateLimited, NetworkUnavailable, ServiceUnavailable
from agent_build_kit.runtimes.base import LoginRejected

if TYPE_CHECKING:
    pass

from agent_build_kit import run_support


def _pr_files(inst: Installation, repo: str, pr: int) -> list[str]:
    forge, repo_id = inst.forge_of(repo)
    return forge.pr_files(repo_id, pr)


def _run_for_verify(command, *, cwd, env=None):
    # A deploy builds images and a blue/green waits on health: long, but not
    # unbounded.
    return subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=3600
    )


class StackBusy(Exception):
    """The live stack is in use and the caller would not wait for it."""


def verify_once(inst: Installation, change: str, units: list) -> Verification:
    """`verify_one`, but a result already on record over the change's current merged units,
    found once the stack lock is held (another worker verified them while this one waited), is
    returned and nothing is deployed."""
    return verify_locked(inst, change, units, wait=None, reuse_recorded=True)


def verify_locked(
    inst: Installation, change: str, units: list, *, wait: float | None, reuse_recorded: bool
) -> Verification:
    # A wait the caller chose is its own; only the configured one names the setting.
    timeout = inst.config.global_limits.e2e_lock_wait_seconds if wait is None else wait
    setting = LOCK_WAIT_SETTING if wait is None else None
    with ExitStack() as held:
        try:
            held.enter_context(
                stack_lock(inst.e2e_lock, timeout, setting, holder=f"verify {change}")
            )
        except TimeoutError as error:
            raise StackBusy(str(error)) from error
        if reuse_recorded:
            last = VerifyRecord(inst.state_dir / "verified.json").get(change)
            if last is not None and last.units == run_support.merged_ids(change, units):
                return last
        outcome = verify_change(
            change,
            units,
            installation=inst,
            pr_files=lambda repo, pr: _pr_files(inst, repo, pr),
            run=_run_for_verify,
            env=inst.verify_env(),
        )
    # Both what is printed and what `verified.json` keeps come from this.
    return outcome.model_copy(update={"detail": redact_text(outcome.detail, where="verify output")})


def verify_and_record(
    inst: Installation, change: str, units: list, verify: Callable[[str, list], Verification]
) -> Verification | None:
    """Verify one change with `verify`, record the outcome in `verified.json` and demote the
    units a failure implicates: the one rule the tick and `abk worker verify` share.

    Returns None, recording nothing, when the live stack is in use or a split is held (the change
    is tried again later). Any other exception is recorded as a failed verification. An outcome
    already on record (another worker verified the same units first) is returned as it is."""
    try:
        outcome = verify(change, units)
    except StackBusy:
        run_support.log(
            f"verifying {change} skipped — the live stack is in use; tried again next round"
        )
        return None
    except SplitHeld as held:
        run_support.log(f"verifying {change} skipped — {held}; tried again next round")
        return None
    except Exception as error:  # noqa: BLE001 — recorded, never silently skipped
        outcome = Verification(
            change=change,
            passed=False,
            detail=f"{type(error).__name__}: {error}",
            units=run_support.merged_ids(change, units),
        )
    record = VerifyRecord(inst.state_dir / "verified.json")
    if record.get(change) == outcome:
        return outcome
    record.put(outcome)
    if outcome.passed:
        run_support.log(f"verified {change}: {', '.join(outcome.deployed) or 'nothing to deploy'}")
    else:
        run_support.log(f"NOT archiving {change} — verification failed:\n{outcome.detail}")
        run_support.demote_failed_verify(inst, change, units)
    return outcome


def resolution_procedure(
    inst: Installation,
    store: UnitStore,
    *,
    moves: run_support.StackMoves,
    move: Callable[..., Moved],
    refusals: set[str],
    defer: Callable[[str, datetime | None], None],
    lane: Callable[[], Lane | None] = lambda: None,
    build: Callable[..., bool] | None = None,
) -> Callable[[StoredUnit], Rest | None]:
    """What is done for a unit owed a resolution run, whoever does it: the lane's worker thread
    or an `abk worker resolve` process. The returned function holds the unit's attempt budget,
    makes the move its state calls for (a restack of a unit in review, a move through `prepare`,
    a move in a temporary tree) with its RESTACK_CONFLICT / RESTACK_DEFERRED bookkeeping, and
    returns what remains: the unit's own run (which checks the unit's lease and branch lock when
    it starts), or None when the move was all there was.

    `refusals` is the set the caller's `refused` hook of `moves` and `move` adds to; `defer` is
    told when the usage guard allows a refused move or a paused run again (a worker, which
    ends, passes a no-op); `lane` returns the lane handed to the run, which gives it to the
    poller (called when the run starts, so a lane may be made after this); `build`
    makes the run (`build_unit` unless the caller reads usage from the snapshot, as a worker
    does)."""

    def run_of(unit_id: str) -> Rest:
        """What remains of a moved-base run once the move is made: the unit's own run, here in
        the lane's worker, flagged as the lane's so a build worker never resumes it."""

        def run() -> None:
            if unit_id in refusals:
                # The guard refused the move's agent: the lane moves it again when it allows.
                refusals.discard(unit_id)
                return
            if Leases(lease_dir(inst.local_dir)).holder(unit_id) is not None:
                raise BranchBusy(f"a tab holds the lease of {unit_id}")
            if run_support.branch_is_held(
                inst, store.get(unit_id).branch or branch_name(store.get(unit_id))
            ):
                raise BranchBusy(f"the branch of {unit_id} is held by another run")
            # The run flags itself once it holds the branch and the unit is runnable.
            (build or build_unit)(
                inst,
                store.get(unit_id),
                store=store,
                moved_base_run=True,
                # A pause that stopped the run: the lane tries it again from the guard's time.
                on_pause=lambda resume_at: defer(unit_id, resume_at),
                lane=lane(),
            )

        return run

    def move_unit(owed: StoredUnit) -> Rest | None:
        unit = store.get(owed.id)
        refusals.discard(unit.id)  # A refusal belongs to the one move that met it.
        if in_a_lane_run(unit):
            return run_of(unit.id)  # An interrupted run: its thread resumes at its node.
        graph = store.all()
        if unit.sent_back_for_rework and not about_the_move(unit):
            # A comment or a change request: the run is the rework, with no attempt to spend.
            return run_of(unit.id)
        if hold_if_spent(inst, store, unit, graph, run_support.log):
            return None
        if unit.sent_back_for_conflict:
            # Sent back for a conflict: the run starts at the move, in this worker.
            return run_of(unit.id)
        repo = inst.checkouts[unit.repo]
        branch = unit.branch or branch_name(unit)
        new_base = base_of(unit, graph)
        old_base = own_work_starts_after(
            repo, local_ref(new_base, repo=unit.repo), unit, store, head=branch
        )
        # What it moves onto is the unit it is built on, or else the trunk it lands on.
        parent = moving_onto(unit, new_base, store)
        if unit.state != RUNNING:
            moves["restack"](
                branch=branch, old_base=old_base, new_base=new_base, child=unit, parent=parent
            )
            left = store.get(unit.id)
            if left.state == PLANNED and left.cause in (
                Cause.RESTACK_CONFLICT,
                Cause.RESTACK_DEFERRED,
            ):
                return run_of(unit.id)
            return None
        if run_support.has_thread(inst, unit.id):
            # Parked at `prepare`: the lane makes the move here, and its worker goes on into
            # the unit's run (`run_of`).
            try:
                ended = advance_thread_through_prepare(inst, unit, store=store)
            except AgentRateLimited as error:
                # The guard refused the resolver: the move is tried again when it allows.
                defer(unit.id, error.resets_at)
                store.set_state(
                    unit.id,
                    RUNNING,
                    note=f"restack onto {new_base} deferred: {cut_head(str(error), 300, 'char')}",
                    cause=Cause.RESTACK_DEFERRED,
                )
                return None
            if ended is not None:
                if ended.conflict:
                    store.set_state(
                        unit.id,
                        PLANNED,
                        note=f"restack onto {new_base} left for its run: its port",
                        cause=Cause.RESTACK_CONFLICT,
                    )
                return run_of(unit.id)
        # A unit with no thread to move through `prepare`: in a worktree of its own it has the
        # branch checked out, where the branch cannot be moved, so the move is left for its
        # run. Without one the branch is moved in a temporary worktree, and a move that
        # cannot be made is left for its run too.
        if unit_tree(repo, branch, inst.worktree_root) is not None:
            store.set_state(
                unit.id,
                RUNNING,
                note=f"restack onto {new_base} left for its run, not a conflict: "
                "its worktree has the branch checked out",
                cause=Cause.RESTACK_CONFLICT,
            )
            return None
        elsewhere = checked_out_elsewhere(repo, branch, inst.worktree_root)
        if elsewhere is not None:
            store.set_state(
                unit.id,
                RUNNING,
                note=f"restack onto {new_base} left for its run, not a conflict: "
                f"{branch} is checked out in {elsewhere}, outside {inst.worktree_root}",
                cause=Cause.RESTACK_CONFLICT,
            )
            return None
        try:
            move(
                repo,
                branch,
                new_base=local_ref(new_base, repo=unit.repo),
                old_base=old_base,
                moving_unit=unit.id,
                moving_change=unit.change,
                moving_repo=unit.repo,
                moving_intent=unit.title,
                onto_unit=parent.id,
                onto_intent=parent.title,
                temporary=TemporaryTree(root=inst.worktree_root, name=unit.repo),
            )
        except AgentRateLimited as error:
            # Refused for usage, not a conflict: still owed, and moved when the guard allows.
            store.set_state(
                unit.id,
                RUNNING,
                note=f"restack onto {new_base} deferred: {cut_head(str(error), 300, 'char')}",
                cause=Cause.RESTACK_DEFERRED,
            )
        except Exception as error:  # noqa: BLE001
            store.set_state(
                unit.id,
                RUNNING,
                note=(
                    f"restack onto {new_base} left for its run: {cut_head(str(error), 300, 'char')}"
                ),
                cause=Cause.RESTACK_CONFLICT,
            )

    return move_unit


class _Run:
    """How a unit's run ended, for its span and its duration: the run's status,
    or why it did not get as far as one."""

    outcome = UnitOutcome.INTERRUPTED


def _git_outage_text(error: Exception) -> str | None:
    """What git said when `error` is the code host refusing or not answering a git call, which
    is what a code host's marker records; None for any other: a forge API outage
    (`HostUnavailable` from the resilient forge, under the name of the API call) is the API's
    host's and parks on its own backoff."""
    if isinstance(error, HostUnavailable) and error.operation == PUSH_OPERATION:
        return error.cause
    if isinstance(error, NetworkUnavailable) and error.service == "code_host":
        return str(error)
    return None


def build_unit(
    inst: Installation,
    unit: Unit,
    *,
    store: UnitStore,
    queued: spans.Mark | None = None,
    moved_base_run: bool = False,
    on_pause: Callable[[datetime | None], None] | None = None,
    lane: Lane | None = None,
    from_snapshot: bool = False,
) -> bool:
    """`_build_unit` as a `unit` span below the tick's, with the run's duration.

    `lane` is the tick's restack lane, which a merge or close recorded when the run ends is
    handed to as the poller's is.

    `from_snapshot` is a worker's: the usage it reads is the snapshot's, never the endpoint.

    `queued` is when the tick first saw the unit ready but for a free slot (see
    `note_queued`): the time from then to its branch lock is recorded as its
    slot wait.

    A unit that has run before links to where that was, so its life across ticks
    can be followed: each run is its own trace, as a pause or a review wait can
    last days."""
    run = _Run()
    started = time.monotonic()
    try:
        earlier = store.get(unit.id).trace
    except KeyError:
        earlier = ""
    attributes = {
        "unit.id": unit.id,
        "change": unit.change,
        "repo": unit.repo,
        "tier": unit.tier,
    }
    with telemetry.tracer().start_as_current_span(
        "unit", attributes=attributes, links=telemetry.links(earlier), **telemetry.SPAN_OPTIONS
    ) as span:
        try:
            return _build_unit(
                inst,
                unit,
                store=store,
                run=run,
                trace=telemetry.reference(span),
                queued=queued,
                moved_base_run=moved_base_run,
                on_pause=on_pause,
                lane=lane,
                from_snapshot=from_snapshot,
            )
        except BaseException:
            telemetry.failed(span)
            raise
        finally:
            if run.outcome is UnitOutcome.FAILED:
                telemetry.failed(span)
            span.set_attribute("outcome", run.outcome)
            elapsed = time.monotonic() - started
            labels = {"repo": unit.repo, "tier": unit.tier, "outcome": str(run.outcome)}
            emit_metric(
                "duration",
                "abk.unit.duration",
                elapsed,
                run_support.log,
                unit=unit.id,
                change=unit.change,
                **labels,
            )


def _build_unit(
    inst: Installation,
    unit: Unit,
    *,
    store: UnitStore,
    run: _Run,
    trace: str = "",
    queued: spans.Mark | None = None,
    moved_base_run: bool = False,
    on_pause: Callable[[datetime | None], None] | None = None,
    lane: Lane | None = None,
    from_snapshot: bool = False,
) -> bool:
    """Start the unit's thread, or resume the one a killed or paused run left,
    and run it to a wait or the end. Returns False only when the model refused
    (rate limited) and the tick should stop.

    The branch's lock is held around the run, from reading the thread's position
    until it returns: a thread waiting for review holds nothing, as the run has
    returned.

    Nothing in here may raise. A tick runs unattended on a timer, so a
    traceback is not a report — it is a unit left in `running` forever and no
    log line saying which one.

    `trace` is where this run is in the traces; it is recorded on the unit only
    once the run is going ahead, so a run that skips never replaces the trace
    of the one that is building the unit.
    """
    branch = branch_name(unit)
    run_log: RunLog | None = None
    ended = "interrupted"
    before: StoredUnit | None = None  # the unit as it was, when this run began an attempt
    agent_ran = False  # whether an agent streamed anything in this run

    def agent_said(message: str) -> None:
        nonlocal agent_ran
        agent_ran = True
        unit_log_only(message)

    def forget_if_not_begun() -> None:
        """A run that stopped before its first agent call was not an attempt: its resume is."""
        if before is not None and not agent_ran:
            forget_run_attempt(store, before)

    def say(message: str) -> None:
        # One stamp for both, so the file lines up with the journal.
        at = run_support.stamp()
        run_support.log(f"{unit.id}: {message}", at=at)
        if run_log is not None:
            run_log.emit(f"[{at}] {message}")

    def journal_only(message: str) -> None:
        run_support.log(f"{unit.id}: {message}", at=run_support.stamp())

    def unit_log_only(message: str) -> None:
        if run_log is not None:
            run_log.emit(f"[{run_support.stamp()}] {message}")

    def end(message: str, outcome: UnitOutcome) -> None:
        nonlocal ended
        ended = message
        run.outcome = outcome
        say(message)

    def park(error: Exception, cause: Cause) -> None:
        """The work is fine and the thread stays at the step: the unit is `planned` with
        `cause`, and the pass readmits it after a backoff, resuming at that step."""
        end(f"parked, {error}", UnitOutcome.INTERRUPTED)
        if cause is Cause.HOST_UNAVAILABLE and (said := _git_outage_text(error)) is not None:
            try:
                code_host.note(inst, unit.repo, said)
            except Exception as second:  # noqa: BLE001 — the marker never keeps a unit from parking
                say(f"the code host's marker could not be written — {second}")
        if cause is Cause.NETWORK_UNAVAILABLE:
            pause_until(
                datetime.now(UTC) + PARK_BACKOFF[0],
                reason=f"network unreachable during {unit.id}",
                marker=network_marker(inst.state_dir),
                kind="network",
            )
        try:
            store.set_state(unit.id, PLANNED, note=str(error), cause=cause)
        except Exception as second:  # noqa: BLE001
            say(f"could not be recorded as parked — {second}")

    def fail(error: Exception) -> None:
        end(f"failed, {type(error).__name__}: {error}", UnitOutcome.FAILED)
        # The error's type and text, and the step it came from, are on the
        # unit's record, not only in a tick log someone would have to find.
        note = f"{type(error).__name__}: {error}"
        try:
            store.set_state(unit.id, UnitState.FAILED, note=note, cause=Cause.FAILED)
        except Exception as second:  # noqa: BLE001
            say(f"could not be recorded as failed — {second}")

    try:
        try:
            with ExitStack() as held:
                held.enter_context(branch_lock(branch, root=inst.locks_dir))
                # The lock holds the unit's place from here, so the marker admission left has
                # done its work; the unit is counted through the lock without a gap.
                run_support.clear_starting(store, unit.id)
                # Re-read under the lock. `ready` comes from the pass's latest
                # evaluation, and ticks overlap to build in parallel: by the time
                # this one reaches a unit, another may have built it and opened its
                # PR. Building it again would re-verify, re-push and re-open that
                # PR. A poll may also have held or closed it since.
                #
                # The whole unit, not only its state: a join may have changed
                # its members since, or removed it into another unit.
                try:
                    unit = store.get(unit.id)
                except KeyError:
                    end("skipped, it was joined into another unit", UnitOutcome.SKIPPED)
                    return True
                # A unit may also be `running`: killed or paused in a node,
                # which is how its thread resumes it.
                # A moved-base run may start from a unit still in review that was sent back
                # for its conflict.
                sent_back = moved_base_run and unit.state == IN_REVIEW and unit.sent_back_for_rework
                if unit.state not in (PLANNED, RUNNING) and not sent_back:
                    end(f"skipped, it is now {unit.state}", UnitOutcome.SKIPPED)
                    return True
                # A tab may have taken the lease since the pass picked this unit. The
                # server writes the lease and then reads the branch lock; this takes the
                # lock and then reads the lease, so one of the two always sees the other.
                if Leases(lease_dir(inst.local_dir)).holder(unit.id) is not None:
                    end("skipped, a tab holds its lease", UnitOutcome.SKIPPED)
                    return True
                if moved_base_run:
                    # The lane's run: flagged only now that it holds the branch and may go on.
                    # A run that starts is an attempt at its base's tip; one resumed is not,
                    # unless the start it resumes stopped before its first agent call.
                    # A comment or change-request rework is no attempt at the base's tip: its
                    # rounds are the review's. A run resumed after a pause has lost the cause
                    # that started it, and is an attempt unless it is a comment's.
                    comment_run = unit.sent_back_for_rework and not about_the_move(unit)
                    if (not unit.moved_base_run or unit.moved_base_uncounted) and not comment_run:
                        tip = base_tip(inst, unit, store.all())
                        if not tip:
                            end("skipped, its base cannot be read", UnitOutcome.SKIPPED)
                            return True
                        before = unit
                        record_run_attempt(store, unit, tip)
                    store.set_moved_base_run(unit.id, True)
                    store.set_moved_base_uncounted(unit.id, False)
                # A step recorded by an earlier run belongs to that run. A parked unit, or one an
                # earlier version's lane handed back, resumes at its node, which never passes
                # `prepare`, so it is marked running here. The cause is standing, so a replan
                # carries it and this reads the same after one.
                if unit.state == PLANNED and (
                    moved_base_run or unit.cause in (*PARKED_CAUSES, Cause.RESTACK_HANDED_BACK)
                ):
                    # A lane run keeps why it was started: `prepare` reads a conflict sent back
                    # from it.
                    store.set_state(
                        unit.id,
                        RUNNING,
                        branch=unit.branch or None,
                        cause=unit.cause if moved_base_run else None,
                    )
                store.record_step(unit.id, "")
                if queued is not None:
                    spans.record_span(
                        queued,
                        say,
                        unit=unit.id,
                        change=unit.change,
                        waited=spans.SLOT,
                    )
                # The base too, from the store rather than that evaluation: a
                # parent may have merged since, and `base_moved` compares against
                # this.
                if trace:
                    store.set_trace(unit.id, trace)
                graph = store.all()
                base = base_of(unit, graph)
                run_log = _start_run_log(inst, unit, store=store, base=base)
                runner = run_support.build_runner(
                    unit,
                    store=store,
                    installation=inst,
                    record_merge=lambda repo, pr: run_support.dispatch_for(inst, store)(
                        "merged", pr, repo=repo
                    ),
                    log=say,
                    log_reaches_run_log=True,
                    journal=journal_only,
                    transcript=agent_said,
                )
                outcome = run_unit_thread(
                    inst, runner, unit, base=base, graph=graph, run_log=run_log
                )
        except ProfileUnsupported as error:
            # A toolchain profile the framework does not implement yet: not the
            # unit's fault, and nothing a retry changes. Held for a person.
            end(f"held — {error}", UnitOutcome.HELD)
            store.set_state(
                unit.id, HELD, note=str(error), held_by=HeldBy.TOOLCHAIN, cause=Cause.TOOLCHAIN
            )
            return True
        except Interrupted as error:
            # Left `running`, with the lock released as the `with` exits: the next
            # tick resumes its thread at the node it was in. Not failed — nothing
            # is known to be wrong.
            end(f"interrupted ({error}); the next tick resumes it", UnitOutcome.INTERRUPTED)
            forget_if_not_begun()
            return True
        except LoginRejected as error:
            # Left `running` and paused for the login (the node recorded it): the account's
            # login is rejected, and the thread resumes at this step when it is renewed.
            end(f"login rejected ({error}); paused until it is renewed", UnitOutcome.INTERRUPTED)
            forget_if_not_begun()
            return True
        except RateLimited as error:
            # Not the unit's fault and not retried: the account is out of room, so
            # marking it failed would drop real work from the plan, and trying the
            # next unit would spend a call to be told the same thing.
            refused_account = claude_account.for_repo(inst.config, unit.repo)
            when = error.resets_at
            if when is None and runtimes.active().supports_usage_tracking:
                # The refusal is the unit's account's, so is the reset it waits for.
                reading = held_usage(refused_account)
                when = reading.resets_at if reading else None
            if on_pause is not None:
                on_pause(error.resets_at)

            # Only the account that was refused is paused.
            state = pause_until(
                when,
                reason=f"rate limited during {unit.id}",
                marker=run_support.paused_marker(inst, refused_account),
                kind="rate_limit",
                account=refused_account.label,
            )
            emit_metric(
                "count",
                "abk.usage.pauses",
                1,
                say,
                unit=unit.id,
                change=unit.change,
                kind="rate_limit",
            )
            end(f"rate limited — {pause_line(state, verb='pausing')}", UnitOutcome.RATE_LIMITED)
            return False
        except BranchBusy as error:
            # Another tick is already on it. Not a failure — marking it one would
            # drop a unit that is going fine out of the plan.
            end(f"skipped, {error}", UnitOutcome.SKIPPED)
            return True
        except HostUnavailable as error:
            park(error, Cause.HOST_UNAVAILABLE)
            return True
        except ServiceUnavailable as error:
            # A status is evidence on its own, so the probe is not asked; a row of them
            # longer than the limit is a fault of the request, not an outage.
            row = store.count_service_attempt(unit.id)
            if row > inst.config.global_limits.service_unavailable_attempts:
                fail(error)
            else:
                park(error, Cause.SERVICE_UNAVAILABLE)
            return True
        except NetworkUnavailable as error:
            # The work is fine: the network or the model's host is down. A strong sign
            # parks on its own evidence; a weak one as the probe sorts it, and a failure
            # the probe does not call an outage is a failure like any other.
            if (cause := run_support.outage_cause(inst, error)) is None:
                fail(error)
                return True
            park(error, cause)
            return True
        except Exception as error:  # noqa: BLE001 — see the docstring.
            fail(error)
            return True

        if outcome.pr_over and outcome.pr is not None:
            # The run ended on a pull request the forge shows merged or closed. The lock is
            # released now, which the handlers need to deliver the event to the unit's thread.
            # A worker has no restack lane to hand the moves to, and a move run in it would
            # skip the lane's usage gate: the poll keeps the event, and the dispatcher's
            # delivers it with its lane.
            if from_snapshot:
                say(f"#{outcome.pr} {outcome.pr_over}: left for a later pass")
            else:
                try:
                    if not run_support.dispatch_for(inst, store, lane=lane)(
                        outcome.pr_over, outcome.pr, repo=unit.repo
                    ):
                        say(f"#{outcome.pr} {outcome.pr_over}: left for a later pass")
                except Exception as error:  # noqa: BLE001
                    say(f"#{outcome.pr} {outcome.pr_over} could not be recorded — {error}")
        end(f"{outcome.status} — {outcome.detail}", outcome.status)
        if outcome.status is UnitOutcome.PAUSED:
            forget_if_not_begun()
            if store.get(unit.id).cause is Cause.LOGIN:
                # A login pause ends when the login is renewed, not at a usage reset: no pause of
                # the whole account for usage, and no usage metric.
                return True
            if on_pause is not None:
                on_pause(outcome.pause.until if outcome.pause else None)
            emit_metric(
                "count", "abk.usage.pauses", 1, say, unit=unit.id, change=unit.change, kind="usage"
            )
            _pause_for_usage(
                inst,
                outcome.pause or PauseInfo(reason=outcome.detail),
                claude_account.for_repo(inst.config, unit.repo),
                from_snapshot=from_snapshot,
            )
        return True
    finally:
        if run_log is not None:
            run_log.close(ended)


def _pause_for_usage(
    inst: Installation,
    pause: PauseInfo,
    account: claude_account.Account,
    *,
    from_snapshot: bool = False,
) -> None:
    """Pause the pipeline for a run the usage guard stopped.

    Re-read rather than reuse the tick's reading: the guard said no after the
    units before this one ran, so the window has moved, and a resume scheduled
    from the stale figure wakes up into a full window. The guard's own answer
    to when, which counts the ramp towards the reset — not the reset itself,
    which it can be well before. A pause that names its own time keeps it.

    With `from_snapshot` (a worker) the reading is the account's usage snapshot, never the
    endpoint.
    """
    start = (
        partial(run_support.decide_start, account=account, from_snapshot=True)
        if from_snapshot
        else partial(run_support.start_decision, [account])
    )
    until = pause.until or build_resume_at(start=start)()
    state = pause_until(
        until,
        reason=pause.reason,
        marker=run_support.paused_marker(inst, account),
        account=account.label,
    )
    run_support.log(run_support.pause_report(inst, state, verb="pausing"))


def _starting_step(inst: Installation, unit: StoredUnit) -> tuple[str, str]:
    """The step a run of this unit starts at, and the model it names: the node
    its thread is positioned at, or `implement` for a build that has none. A
    review of a rework is named apart, as it is judged by its own model; the
    steps that call no model say so."""
    where = run_support.thread_of(inst, unit.id)
    node = where.next[0] if where.next else Node.IMPLEMENT
    reworking = where.state is not None and where.state.had_feedback
    step = "rework_review" if node is Node.REVIEW and reworking else node.value
    role = config.models()
    named = {
        "rework_review": role.rework_review,
        Node.REVIEW.value: role.review,
        Node.REWORK.value: role.rework,
        Node.TESTS.value: role.implement,
        Node.IMPLEMENT.value: role.implement,
    }
    return step, named.get(step, "none")


def _start_run_log(inst: Installation, unit: StoredUnit, *, store: UnitStore, base: str) -> RunLog:
    step, model = _starting_step(inst, unit)
    run_log = RunLog(
        orchestration.get(ARTIFACTS, inst),
        unit,
        step=step,
        model=model,
        base=base,
        started=datetime.now(UTC),
        report=lambda message: run_support.log(f"{unit.id}: {message}"),
    )
    if run_log.writing:
        store.set_run_log(unit.id, run_log.name)
    return run_log


def run_unit_thread(
    inst: Installation,
    runner: UnitRunner,
    unit: Unit,
    *,
    base: str,
    graph: list[StoredUnit],
    run_log: RunLog | None,
) -> RunOutcome:
    """Start or resume the unit's thread to its next wait or the end."""
    return asyncio.run(
        run_support.on_thread(inst, runner, unit, base=base, graph=graph, run_log=run_log)
    )


def advance_thread_through_prepare(
    inst: Installation, unit: StoredUnit, *, store: UnitStore
) -> UnitRun | None:
    """Run the unit's thread through `prepare` and no further, the move onto its moved base
    that `prepare` makes, leaving the thread for a build slot; the state it ends in. None when
    the thread is not parked at `prepare`. The caller holds the unit's branch."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.unit import advance_through_prepare
    from agent_build_kit.orchestration.checkpoints import open_checkpoints

    make_runner, base, graph = run_support.thread_runner(
        inst, unit, store, run_support.unit_log(unit)
    )

    async def advance() -> UnitRun | None:
        async with open_checkpoints(inst) as saver:
            return await advance_through_prepare(
                make_runner, unit, base=base, graph=graph, saver=saver, tracer=telemetry.tracer()
            )

    return asyncio.run(advance())
