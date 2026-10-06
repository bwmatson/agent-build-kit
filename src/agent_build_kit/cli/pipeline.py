"""The tick the timer runs, and the commands beside it: status, graph, verify.

One tick, in order: check the usage window, poll GitHub, plan what is new,
verify and archive what has fully merged, work out what is ready, and build
it. Each step is tested on its own; this is the wiring, kept thin enough to
read in one sitting.

It is safe to run at any moment, which is what lets a timer call it every few
minutes. Every step is idempotent: the store keeps unit state across
processes, and a branch lock stops two ticks building the same unit.

Every function takes the `Installation` explicitly — where the state is, where
the specs are, which repos exist — rather than reading module globals, so a
test can point one at a temporary planning repo.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager, ExitStack
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from agent_build_kit import config, forges, runtimes, telemetry
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import diagram, spans, usage_report
from agent_build_kit.pipeline.archive import (
    _already_archived,
    archive_ready_changes,
    is_ready_to_archive,
)
from agent_build_kit.pipeline.drafts import StateDrafts
from agent_build_kit.pipeline.events import (
    build_claim,
    build_delete_branch,
    build_dispatch,
    build_fetch_check_logs,
    build_fetch_review,
    build_remove_worktree,
    build_rerun_checks,
    build_restack,
    build_retarget,
)
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.joins import JoinContext
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.pause import clear_pause, is_paused, pause_until
from agent_build_kit.pipeline.planner import GroupTooLarge, in_flight_item, plan_round
from agent_build_kit.pipeline.planning_repo import (
    default_branch_of,
    is_repo,
    restore_default_branch,
)
from agent_build_kit.pipeline.pr_poller import Poller, state_path, unmergeable
from agent_build_kit.pipeline.pr_replies import ignored
from agent_build_kit.pipeline.restack import push_with_lease, resolved_move
from agent_build_kit.pipeline.run_log import RunLog, remove_change_logs, run_log_dir
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus, UnitRunner
from agent_build_kit.pipeline.tier2 import stack_lock
from agent_build_kit.pipeline.unit_store import UNPLANNED, HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_FLIGHT,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    Join,
    Unit,
    base_of,
    branch_name,
    held_for_base,
    in_progress,
    in_progress_label,
    local_ref,
    ready_units,
    start_room,
    trunk_of,
)
from agent_build_kit.pipeline.usage_guard import (
    Interrupted,
    Limits,
    RateLimited,
    UsageReading,
    current_usage,
    may_start_unit,
    threshold_at,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.verify import Verification, VerifyRecord, verify_change
from agent_build_kit.pipeline.wiring import (
    CommitRejected,
    build_resume_at,
    build_runner,
)
from agent_build_kit.pipeline.work_graph import (
    NEEDS_LINE,
    group_needs,
    validate_tasks,
)
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_lock

if TYPE_CHECKING:
    from agent_build_kit.graph.unit import Position


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(message: str, *, at: str | None = None) -> None:
    print(f"[{at or stamp()}] {message}", flush=True)


def store_for(inst: Installation) -> UnitStore:
    def refresh_graph(units: list[StoredUnit]) -> None:
        # A view, so it must never take the store write down with it.
        try:
            diagram.write_page(units, inst.graph_page)
        except Exception as error:  # noqa: BLE001
            log(f"graph not refreshed — {type(error).__name__}: {error}")

    def refresh_usage(units: list[StoredUnit]) -> None:
        try:
            usage_report.write_page(units, inst.state_dir / LEDGER_NAME, inst.usage_page)
        except Exception as error:  # noqa: BLE001
            log(f"usage page not refreshed — {type(error).__name__}: {error}")

    def refresh_pages(units: list[StoredUnit]) -> None:
        refresh_graph(units)
        refresh_usage(units)

    labels = StateLabels(inst.forge_of, log=log)
    drafts = StateDrafts(inst.forge_of, log=log)

    def follow(unit: StoredUnit, units: list[StoredUnit], opened: bool) -> None:
        labels.follow(unit, units, opened=opened)
        drafts.follow(unit, units, opened=opened)

    return UnitStore(
        inst.state_dir / "units.json",
        on_write=refresh_pages,
        on_state=follow,
    )


def _paused_marker(inst: Installation) -> Path:
    return inst.state_dir / "paused.json"


# --- status / graph -------------------------------------------------------------


def _usage_line(reading: UsageReading) -> str:
    """Each window's usage against the threshold that applies to it *now*.

    The threshold moves as a window nears its reset, so printing the configured
    floor alone would leave `abk status` unable to explain why a run at 78% was
    allowed, or a pause at 71% was not lifted.
    """
    limits = Limits.configured()
    now = datetime.now(UTC)

    parts = []
    for window in reversed(reading.windows):
        threshold = threshold_at(window, now=now, limits=limits)
        detail = f"{window.used_pct}%/{threshold}%"
        if window.resets_at:
            minutes = max(0, int((window.resets_at - now).total_seconds() // 60))
            detail += f", resets in {minutes // 60}h{minutes % 60:02d}m"
        parts.append(f"{window.name} {detail}")
    return ", ".join(parts)


def cmd_status(args: argparse.Namespace, inst: Installation) -> int:
    """What the pipeline thinks is going on, without changing anything."""
    paused = is_paused(_paused_marker(inst))
    if paused:
        log(f"paused until {paused.until:%Y-%m-%d %H:%M UTC} — {paused.reason}")

    try:
        runtime = runtimes.active()
    except KeyError as exc:
        log(f"usage: runtime {config.runtime_name()} is not available: {exc}")
    else:
        reading = current_usage() if runtime.supports_usage_tracking else None
        if not runtime.supports_usage_tracking:
            log(f"usage: runtime {runtime.name} has no usage window")
        elif reading:
            log(f"usage: {_usage_line(reading)} ({reading.source})")
        else:
            log("usage: unknown")

    units = store_for(inst).all()
    if not units:
        log("no units planned")
        return 0

    by_state: dict[str, int] = {}
    for unit in units:
        by_state[unit.state] = by_state.get(unit.state, 0) + 1
    log("units: " + ", ".join(f"{count} {state}" for state, count in sorted(by_state.items())))

    # What the last poll of each repo saw: an entry that cannot be merged is not
    # actionable, so it should not read like the others.
    conflicted: dict[str, set[int]] = {}

    full = _queue_full_line(inst, units)
    if full:
        log(full)

    for unit in units:
        if unit.state == IN_REVIEW:
            if unit.repo not in conflicted:
                conflicted[unit.repo] = unmergeable(state_path(inst.state_dir, unit.repo))
            mark = " — cannot be merged" if unit.pr in conflicted[unit.repo] else ""
            log(f"  awaiting review: {unit.id} ({unit.repo}) #{unit.pr or '?'}{mark}")
    return 0


def cmd_graph(args: argparse.Namespace, inst: Installation) -> int:
    units = UnitStore(inst.state_dir / "units.json").all()
    diagram.write_page(units, inst.graph_page)
    print(f"{inst.graph_page}: {len(units)} unit(s)")
    return 0


# --- verify -------------------------------------------------------------------------


def _pr_files(inst: Installation, repo: str, pr: int) -> list[str]:
    forge, repo_id = inst.forge_of(repo)
    return forge.pr_files(repo_id, pr)


def _run_for_verify(command, *, cwd, env=None):
    # A deploy builds images and a blue/green waits on health: long, but not
    # unbounded.
    return subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=3600
    )


def verify_one(inst: Installation, change: str, units: list) -> Verification:
    """Deploy one merged change and run its live tests — under the stack
    lock, since both touch the one live stack tier 2 also uses."""
    with stack_lock(inst.state_dir / "tier2.lock"):
        return verify_change(
            change,
            units,
            installation=inst,
            pr_files=lambda repo, pr: _pr_files(inst, repo, pr),
            run=_run_for_verify,
            env=inst.verify_env(),
        )


def _merged_ids(change: str, units: list) -> list[str]:
    # The same rule `verify_change` records its units by: a merged unit with a PR.
    return sorted(u.id for u in units if u.carries(change) and u.state == MERGED and u.pr)


def _unverified(inst: Installation, units: list, record: VerifyRecord) -> list[str]:
    """Changes ready to archive, not archived, and with no verification on
    record over their current merged units."""
    specs_dir = inst.config.planning.specs_dir
    changes = {
        m.change
        for u in units
        for m in u.members()
        if is_ready_to_archive(m.change, units)
        and not _already_archived(m.change, inst.root, specs_dir)
    }
    return sorted(
        change
        for change in changes
        if (last := record.get(change)) is None or last.units != _merged_ids(change, units)
    )


def verify_ready(
    inst: Installation, units: list, *, verify: Callable | None = None
) -> Callable[[str], bool]:
    """Verify every change that is ready to archive and not yet verified over
    its current merged units; return whether a change may archive.

    A failure is kept, not retried: the same units fail the same way until a
    fix merges (a new unit, so verified again) or a person runs `verify`.
    """
    verify = verify or (lambda change, units: verify_one(inst, change, units))
    record = VerifyRecord(inst.state_dir / "verified.json")
    for change in _unverified(inst, units, record):
        merged = _merged_ids(change, units)
        log(f"verifying {change} live: deploy, then its live-stack tests")
        try:
            outcome = verify(change, units)
        except Exception as error:  # noqa: BLE001 — recorded, never silently skipped
            outcome = Verification(
                change=change, passed=False, detail=f"{type(error).__name__}: {error}", units=merged
            )
        record.put(outcome)
        if outcome.passed:
            log(f"verified {change}: {', '.join(outcome.deployed) or 'nothing to deploy'}")
        else:
            log(f"NOT archiving {change} — verification failed:\n{outcome.detail}")

    def may_archive(change: str) -> bool:
        last = record.get(change)
        return last is not None and last.passed

    return may_archive


def cmd_verify(args: argparse.Namespace, inst: Installation) -> int:
    """Verify one change by hand — after fixing what made it fail — and
    archive it if it passes: the tick sees no work once everything merged."""
    units = store_for(inst).all()
    outcome = verify_one(inst, args.change, units)
    VerifyRecord(inst.state_dir / "verified.json").put(outcome)
    if not outcome.passed:
        print(f"{args.change}: verification failed\n{outcome.detail}")
        return 1
    print(f"{args.change}: verified — {', '.join(outcome.deployed) or 'nothing to deploy'}")
    for change in archive_ready_changes(
        units,
        planning_repo=inst.root,
        may_archive=lambda change: change == args.change,
        specs_dir=inst.config.planning.specs_dir,
        run_logs=run_log_dir(inst.state_dir),
        usage_ledger=inst.state_dir / LEDGER_NAME,
    ):
        print(f"archived {change}")
    return 0


# --- the tick ---------------------------------------------------------------------------


def cmd_tick(args: argparse.Namespace, inst: Installation) -> int:
    """One pass of the loop. Safe to call at any time.

    Ordering matters in one place: the usage check comes first, so a low
    window stops the tick before it spends anything on planning.
    """
    if is_repo(inst.root) and not restore_default_branch(
        inst.root, default_branch_of(inst.root), log
    ):
        return 1

    # First, and silently: the timer fires every few minutes whether or not
    # there is anything to do, and an idle tick should cost nothing — not a
    # usage read, not a GitHub call, not a log line each time, not a span.
    if not has_work(inst, store_for(inst)):
        return 0

    recording = telemetry.init()
    tick = _Tick()
    started = time.monotonic()
    try:
        with telemetry.tracer().start_as_current_span("tick", **telemetry.SPAN_OPTIONS) as span:
            try:
                return _tick(args, inst, tick)
            except BaseException:
                telemetry.failed(span)
                raise
    except BaseException:
        tick.outcome = "error"
        raise
    finally:
        telemetry.duration("abk.tick.duration", time.monotonic() - started, outcome=tick.outcome)
        if recording:
            _record_unit_states(inst)
        # Before returning: a tick is a short-lived process, and what it
        # recorded would be lost at exit.
        telemetry.shutdown()


class _Tick:
    """How a tick ended, for its duration's `outcome`: `built` unless it says otherwise."""

    outcome = "built"


UNIT_GAUGE_STATES = (PLANNED, RUNNING, IN_REVIEW, HELD, FAILED)


def _record_unit_states(inst: Installation) -> None:
    """How many units stand in each state that wants attention, as the tick ends."""
    try:
        states = [unit.state for unit in store_for(inst).all()]
    except Exception:  # noqa: BLE001 — telemetry never affects a tick.
        return
    for state in UNIT_GAUGE_STATES:
        telemetry.level("abk.units", states.count(state), state=state)


def _tick(args: argparse.Namespace, inst: Installation, tick: _Tick) -> int:
    """What a tick does once there is work: the pause checks, the refresh and
    planning, then the builds."""
    # A pause is not a lock: the guard is asked again on every tick, so a
    # threshold raised by hand, or the ramp offering room before the reset,
    # ends it at the next tick. Only the model's own refusal is kept to its
    # deadline. See `pause`.
    paused = is_paused(_paused_marker(inst))
    if paused and paused.kind == "rate_limit":
        log(f"paused until {paused.until:%H:%M UTC} — {paused.reason}")
        # A pause builds nothing, so a unit no run holds should read `planned`
        # for as long as it lasts. Not otherwise: a tick that goes on resumes it.
        reclaim_stranded(inst, store_for(inst))
        tick.outcome = "paused"
        return 0

    # The usage window is Claude Code's. A runtime without one is not held by it:
    # the account's window says nothing about an on-demand agent. Its own
    # rate-limit refusal still pauses, above and in `_run_unit`.
    runtime = runtimes.active()
    if runtime.supports_usage_tracking:
        reading = current_usage()
        decision = may_start_unit(reading)
        if not decision.may_start:
            state = pause_until(
                decision.resume_at, reason=decision.reason, marker=_paused_marker(inst)
            )
            log(
                f"{'paused' if paused else 'pausing'} until {state.until:%H:%M UTC}"
                f" — {decision.reason}"
            )
            if not paused:
                # A new pause; the ticks that find it still in force are not more of them.
                telemetry.count("abk.usage.pauses", kind="usage")
            reclaim_stranded(inst, store_for(inst))
            tick.outcome = "paused"
            return 0
        reason = decision.reason
    else:
        reason = f"runtime {runtime.name} has no usage window; not checking one"

    if paused:
        log(f"resuming a pause that was to last until {paused.until:%H:%M UTC}")
    clear_pause(_paused_marker(inst))
    log(reason)

    store = store_for(inst)

    # Before anything is scheduled: a PR that merged since the last tick frees
    # a depth slot and changes what the branches above it should sit on, so
    # planning against the pre-poll graph builds against a stale picture.
    # Before polling: a merge the poll finds restacks the units above it
    # straight away, and they must land on the trunk as it now is.
    _refresh(inst, store=store)

    convert_in_flight(inst, store=store)
    plan_all(inst, store=store)
    link_needs(inst, store=store)
    units = store.all()

    may_archive = verify_ready(inst, units)
    archived = archive_ready_changes(
        units,
        planning_repo=inst.root,
        may_archive=may_archive,
        specs_dir=inst.config.planning.specs_dir,
        run_logs=run_log_dir(inst.state_dir),
        usage_ledger=inst.state_dir / LEDGER_NAME,
    )
    for change in archived:
        log(f"archived {change}")

    # Everything else still happens — polling, planning, archiving — so the
    # store stays current; only building is narrowed. For pushing one unit
    # through when usage is tight, without a second competing for it.
    only = frozenset(getattr(args, "only", None) or ())
    if only:
        log(f"--only: building nothing but {', '.join(sorted(only))}")
    ready = [
        *resumable_units(inst, units, only=only),
        *_evaluate(inst, units, started=set(), building=set(), only=only),
    ]
    if not ready:
        log(_nothing_started_reason(inst, units, only=only))
        tick.outcome = "idle"
        return 0

    log(f"ready: {', '.join(unit.id for unit in ready)}")
    if args.dry_run:
        log("dry run — stopping before any unit is built")
        tick.outcome = "dry_run"
        return 0

    # Here rather than at the commit step: catching it there would mean
    # paying for two Claude runs first, and again every tick. After the dry
    # run returns, so `--dry-run` still reports what is pending.
    if _refuse_unconfigured(inst, ready):
        tick.outcome = "refused"
        return 1

    return _schedule(inst, ready, store=store, only=only)


def reclaim_stranded(inst: Installation, store: UnitStore) -> None:
    """Return to `planned` each unit marked `running` that no process holds
    and no thread can resume: its run was killed before it reached a point to
    resume from. One a live process holds, or with a thread, is left."""
    for unit in store.all():
        if (
            unit.state == RUNNING
            and not branch_is_held(inst, unit.branch or branch_name(unit))
            and not has_thread(inst, unit.id)
        ):
            store.set_state(unit.id, PLANNED, note="requeued: its run ended without a thread")
            telemetry.count("abk.units.reclaimed")
            log(f"{unit.id}: no run holds it — planned again")


def resumable_units(
    inst: Installation, units: list[StoredUnit], *, only: frozenset[str]
) -> list[Unit]:
    """The units whose thread a run left partway: killed in a node, or
    interrupted for the usage window, which the guard let this tick through.
    They are `running`, so they hold the slots `_evaluate` counts; a thread
    waiting for review or a person is not here, and holds none."""
    return [
        unit
        for unit in units
        if unit.state == RUNNING
        and (not only or unit.id in only)
        and not branch_is_held(inst, unit.branch or branch_name(unit))
        and has_thread(inst, unit.id)
    ]


def _evaluate(
    inst: Installation,
    units: list[StoredUnit],
    *,
    started: set[str],
    building: set[str],
    only: frozenset[str],
    enforce_limit: bool = True,
    max_concurrent: int | None = None,
) -> list[Unit]:
    """What this pass may start now.

    `ready_units` decides from the stored state alone, which lags the pass: a
    unit just handed to the pool is still `planned` until its build marks it
    `running`, and one whose build ended held is `planned` again. So the
    graph it sees counts every build in flight as running — keeping the
    concurrency cap and blocking its dependents until it finishes — and shows
    what this pass has already started, or `--only` excludes, as held. The
    answer is filtered again too: never handing a unit out twice is what
    guarantees the pass ends.
    """
    view: list[Unit] = []
    for unit in units:
        if unit.id in building:
            unit = unit.model_copy(update={"state": RUNNING})
        elif unit.state == PLANNED and (unit.id in started or (only and unit.id not in only)):
            unit = unit.model_copy(update={"state": HELD})
        view.append(unit)
    ready = ready_units(
        view,
        max_concurrent=max_concurrent or inst.max_concurrent_stacks,
        depth_cap=inst.stack_depth_build_cap,
        max_units_in_progress=inst.max_units_in_progress if enforce_limit else None,
    )
    return [unit for unit in ready if unit.id not in started]


def _queue_full_line(inst: Installation, units: list[StoredUnit]) -> str | None:
    held = [unit for unit in units if in_progress(unit)]
    if start_room(units, inst.max_units_in_progress):
        return None
    by_label: dict[str, int] = {}
    for unit in held:
        label = in_progress_label(unit)
        by_label[label] = by_label.get(label, 0) + 1
    states = ", ".join(f"{count} {label}" for label, count in sorted(by_label.items()))
    return (
        f"queue is full: {len(held)} units in progress, limit {inst.max_units_in_progress} "
        f"({states})"
    )


def _nothing_started_reason(
    inst: Installation, units: list[StoredUnit], *, only: frozenset[str]
) -> str:
    """Why a pass starts nothing: the limit, when lifting it would start a
    unit, and otherwise that nothing is ready."""
    full = _queue_full_line(inst, units)
    if full and _evaluate(
        inst, units, started=set(), building=set(), only=only, enforce_limit=False
    ):
        return f"{full}; no new unit starts until one finishes or is closed"
    return "nothing ready to build"


def _refuse_unconfigured(inst: Installation, ready: list[Unit]) -> bool:
    unconfigured = [repo for repo in {unit.repo for unit in ready} if not has_identity(inst, repo)]
    if unconfigured:
        log(
            f"refusing to build: git has no identity for {', '.join(sorted(unconfigured))}, "
            "so an agent's commits would be attributed to nobody. Set one globally with "
            "`git config --global user.email <email>` (and user.name), or for this repo "
            "alone with `git -C <repo> config user.email <email>`."
        )
    return bool(unconfigured)


# How often a pass looks at GitHub while builds are running, matching the tick
# timer's cadence. Waiting for a completion alone left a pass with one long
# build — a tier 2 run, a slow review — blind for its whole length, and the
# timer cannot start a second tick while this one is running.
REFRESH_SECONDS = 300.0

# How many times a pass may start a unit that it already built and that a poll
# then sent back (a conflict, a failing check, a review comment). Bounded so a
# pass still ends.
REBUILDS_PER_PASS = 2


def _sent_back(
    units: list[StoredUnit], started: dict[str, datetime], building: set[str]
) -> set[str]:
    """Units this pass already built that have since been put back to planned:
    sent back for rework by a poll, or held by their own build because the
    branch it builds on changed (see `held_for_base`). A unit held for any other
    reason waits for the next pass: a rerun would meet the same cause."""
    out: set[str] = set()
    for unit in units:
        at = started.get(unit.id)
        if at is None or unit.id in building or unit.state != PLANNED or not unit.history:
            continue
        last = unit.history[-1]
        note = str(last.get("note", ""))
        if not (note.startswith("rework requested") or held_for_base(note)):
            continue
        try:
            when = datetime.fromisoformat(str(last.get("at", "")))
        except ValueError:
            continue
        if when > at:
            out.add(unit.id)
    return out


def _schedule(
    inst: Installation,
    ready: list[Unit],
    *,
    store: UnitStore,
    only: frozenset[str],
) -> int:
    """Keep the build slots full until nothing more is ready.

    Every completion may release something — a parent's PR opening lets its
    child stack on it, a dependency merging releases its dependent — so each
    one is followed by a refresh from GitHub and a fresh evaluation, rather
    than waiting for the whole batch and the next tick. The refresh asks
    GitHub rather than hearing from it, since a tick has no endpoint for a
    webhook to reach; a completion is when it asks. A build reporting that
    the pass should stop, or a pause recorded meanwhile, ends submission; the
    builds already running are still awaited, since each checks the usage
    guard itself and killing one would leave its work uncommitted.

    The refresh runs while other builds are still going, so what it hears may
    concern one of them. The event handlers leave a unit whose build holds its
    lock untouched and the poller reports the event again later — see
    `events` — which the refresh after that build's own completion does.

    A repo found mid-pass with no commit identity stops submission for every
    repo, not only that one, for the rest of the pass; the builds in flight
    are still awaited and the pass exits 1, as it does when the check fails
    at the start.
    """
    started: dict[str, datetime] = {}
    rebuilt: dict[str, int] = {}
    readmitted: set[str] = set()
    building: dict[Future[bool], Unit] = {}
    # Units that could build but for the slots, from when they were first seen so.
    queued: dict[str, spans.Mark] = {}
    stopping = False
    refused = False
    with ThreadPoolExecutor(
        max_workers=inst.max_concurrent_stacks, thread_name_prefix="unit"
    ) as pool:

        def note_queued(units: list[StoredUnit], ready: list[Unit], in_flight: set[str]) -> None:
            """Start the clock on each unit that could build but for the slots:
            the ones the readiness rules return with the concurrency cap lifted
            and that are neither in `ready` nor building."""
            taken = in_flight | {unit.id for unit in ready}
            evaluated = _evaluate(
                inst,
                units,
                started=set(started),
                building=in_flight,
                only=only,
                max_concurrent=len(units) + 1,
            )
            # A unit that stopped being ready restarts its clock when it is again.
            for unit_id in set(queued) - {unit.id for unit in evaluated}:
                del queued[unit_id]
            for unit in evaluated:
                if unit.id not in taken:
                    queued.setdefault(unit.id, spans.Mark())

        def submit(units: list[Unit]) -> None:
            for unit in units:
                started[unit.id] = datetime.now(UTC)
                # The tick's span goes into the worker by its context: a
                # pool's threads do not inherit it.
                work = contextvars.copy_context()
                run = partial(
                    build_unit,
                    inst,
                    unit,
                    store=store,
                    queued=queued.pop(unit.id, None),
                )
                building[pool.submit(work.run, run)] = unit

        note_queued(store.all(), ready, set())
        submit(ready)
        # Each round waits for a build to finish or for REFRESH_SECONDS,
        # whichever is first, then refreshes and fills free slots. The pass
        # ends once none is in flight.
        while building:
            done, _ = wait(building, timeout=REFRESH_SECONDS, return_when=FIRST_COMPLETED)
            for future in done:
                building.pop(future)
                if not future.result():
                    stopping = True
            # A build still in flight — or another tick — may already have
            # paused the pipeline; its report is not needed to stop here.
            stopping = stopping or bool(is_paused(_paused_marker(inst)))
            if stopping or refused:
                continue

            _refresh(inst, store=store)
            units = store.all()
            in_flight = {unit.id for unit in building.values()}
            # A unit this pass built and that has since been put back — sent
            # back by a poll, or held by its own build because its base moved
            # — is due again now, not in the next pass, which cannot start
            # until this one ends.
            for unit_id in _sent_back(units, started, in_flight):
                if rebuilt.get(unit_id, 0) < REBUILDS_PER_PASS:
                    started.pop(unit_id)
                    readmitted.add(unit_id)
            ready = _evaluate(
                inst,
                units,
                started=set(started),
                building=in_flight,
                only=only,
            )
            # The budget is spent when a unit is started again, not when it is
            # let back in: a held unit may wait several rounds on what it was
            # held for, and must not run out before it can run.
            for unit in ready:
                if unit.id in readmitted:
                    readmitted.discard(unit.id)
                    rebuilt[unit.id] = rebuilt.get(unit.id, 0) + 1
            note_queued(units, ready, in_flight)
            if ready:
                log(f"ready: {', '.join(unit.id for unit in ready)}")
                if _refuse_unconfigured(inst, ready):
                    refused = True
                    continue
                submit(ready)
    return 1 if refused else 0


def _refresh(inst: Installation, *, store: UnitStore) -> None:
    """Fetch and poll, as the top of the tick does: a merge only a poll
    reveals may release a dependent, and review feedback should not wait for
    a pass that now lasts as long as its longest build.

    Neither may end the pass. `fetch_all` logs a failed fetch itself, but
    taking a repo's lock or choosing its token can still raise; builds then
    go on from what was last fetched."""
    try:
        fetch_all(inst)
    except Exception as error:  # noqa: BLE001
        log(f"fetch skipped — {type(error).__name__}: {error}")
    try:
        poll_all(inst, store=store)
    except Exception as error:  # noqa: BLE001
        # GitHub being unreachable is a reason to skip the update, not to stop
        # building units whose work doesn't depend on it.
        log(f"poll skipped — {type(error).__name__}: {error}")


def branch_is_held(inst: Installation, branch: str) -> bool:
    """Whether a live process holds this branch's lock.

    `branch_lock` already distinguishes a crashed holder from a live one by
    its pid; acquiring and releasing is the cheapest way to ask.
    """
    try:
        with branch_lock(branch, root=inst.state_dir / "locks"):
            return False
    except BranchBusy:
        return True


def thread_of(inst: Installation, unit_id: str) -> Position:
    """Where the unit's thread stands; its `state` is None when it has none."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
    from agent_build_kit.graph.unit import thread_position

    async def look() -> Position:
        async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
            return await thread_position(saver, unit_id)

    return asyncio.run(look())


def has_thread(inst: Installation, unit_id: str) -> bool:
    """Whether a thread exists for the unit."""
    return thread_of(inst, unit_id).state is not None


def convert_in_flight(inst: Installation, *, store: UnitStore) -> None:
    """Seed a thread for each unit the engine before the switch left in flight, at the
    start of a tick: units that already have one are left where they are."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
    from agent_build_kit.graph.convert import convert_units_in_flight

    async def convert() -> tuple[str, ...]:
        async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
            return await convert_units_in_flight(saver, store)

    for unit_id in asyncio.run(convert()):
        log(f"{unit_id}: moved onto a thread")


def link_needs(inst: Installation, *, store: UnitStore) -> None:
    """Apply every change's `Needs:` lines as unit dependencies.

    Every tick, after planning: a re-plan takes each unit's dependencies from
    the plan, which knows nothing of these, so linking once would not last.
    Idempotent — a dependency already there is left alone.
    """
    units = store.all()
    covering = {
        (member.change, group): unit.id
        for unit in units
        if unit.state != UNPLANNED
        for member in unit.members()
        for group in member.groups
    }
    wanted: dict[str, list[str]] = {}
    gated: dict[str, list[str]] = {}
    for tasks in inst.tasks_files():
        change = tasks.parent.name
        for group, found in group_needs(tasks).items():
            for missing in (n for n in found if (n.change, n.group) not in covering):
                log(
                    f"{change} group {group} needs {missing.change} group {missing.group}, "
                    "not planned yet"
                )
            for unit in units:
                if unit.state == UNPLANNED or not any(
                    member.change == change and group in member.groups for member in unit.members()
                ):
                    continue
                for need in found:
                    if (need.change, need.group) in covering:
                        target = covering[(need.change, need.group)]
                        wanted.setdefault(unit.id, []).append(target)
                        if need.merged:
                            gated.setdefault(unit.id, []).append(target)
    for unit in units:
        if unit.id not in wanted and not unit.merge_before:
            continue
        add = wanted.get(unit.id, [])
        linked = tuple(dict.fromkeys((*unit.depends_on, *add)))
        if linked != unit.depends_on:
            store.set_dependencies(unit.id, linked)
            log(f"{unit.id}: now depends on {', '.join(add)} (Needs: in tasks.md)")
        # Recomputed from tasks.md, not unioned with what is stored: dropping
        # `merged` from a Needs: line releases the unit, and that edit does not
        # change the plan hash, so nothing else would clear it.
        held = tuple(dict.fromkeys(g for g in gated.get(unit.id, []) if g in linked))
        if held != unit.merge_before:
            store.set_merge_before(unit.id, held)


def plan_all(inst: Installation, *, store: UnitStore) -> None:
    """Turn each OpenSpec change into units, when it needs it.

    Planning is a model call, and a tick runs every few minutes — so a change
    is planned once, and again only when its `tasks.md` changes. The recorded
    hash is machine-local and losing it is harmless: `upsert` merges by unit
    id and keeps state, branch and PR, so re-planning costs a model call and
    nothing else.
    """
    planned = _planned_hashes(inst)
    max_attempts = inst.max_plan_attempts

    for tasks in inst.tasks_files():
        change = tasks.parent.name
        digest = hashlib.sha256(specification(tasks).encode()).hexdigest()
        record = planned.get(change) or {}

        # Attempts are counted against the content, not the change, so editing
        # tasks.md — which is the actual fix — starts them over.
        if record.get("hash") == digest:
            if record.get("ok"):
                continue
            if record.get("attempts", 0) >= max_attempts:
                continue

        # The tags are how a unit finds its repo and its tier. Planning
        # against a broken one spends a model call to produce a graph that
        # cannot be built, so this refuses before paying for it.
        task_groups, errors = validate_tasks(tasks, repos=tuple(inst.repos))
        if errors:
            log(f"not planning {change}: {len(errors)} task-group problem(s) — run `abk tags`")
            continue

        # Merged units included, not just in-flight ones: a re-plan after some
        # units merged has to know they exist, or it either re-plans work that
        # is already in main or drops those groups — which the graph check then
        # rejects, leaving the change unplannable. Satisfied units too: they
        # never merge, but their groups are as done as a merged unit's.
        # Planned units of other changes too: the unstarted ones are what the
        # planner may join this change's groups to, or join to each other.
        context = [
            in_flight_item(u)
            for u in store.all()
            if u.state in (*IN_FLIGHT, MERGED, SATISFIED)
            or (u.state == PLANNED and u.change != change)
        ]
        try:
            # The groups go in so the plan is checked against the tags, which
            # were validated on the change's own PR: a model handing one
            # repo's group to another repo's unit is a real failure mode.
            # Groups already accounted for by a unit nobody is going to
            # re-plan — merged, or in flight right now — are passed as built:
            # without them the check demands every group appear in the new
            # plan, which makes a change unplannable the moment any part of
            # it starts.
            # Groups another change's planned unit carries are as claimed.
            built = {
                number
                for u in store.all()
                if u.state in (*IN_FLIGHT, MERGED, SATISFIED)
                or (u.state == PLANNED and u.change != change)
                for member in u.members()
                if member.change == change
                for number in member.groups
            }
            plan = plan_round(
                changes={change: tasks.read_text()},
                in_flight=context,
                groups=task_groups,
                built=built,
                # Units the store already has: a dependency naming one of
                # them is not a dependency on nothing.
                known={u.id for u in store.all()},
                context=JoinContext(
                    stored=tuple(store.all()),
                    catalog={
                        path.parent.name: tuple(validate_tasks(path, repos=tuple(inst.repos))[0])
                        for path in inst.tasks_files()
                    },
                    needs={
                        group: tuple((need.change, need.group) for need in found)
                        for group, found in group_needs(tasks).items()
                    },
                ),
            )
        except GroupTooLarge as error:
            # Fixed in tasks.md, not in the plan: every attempt is spent at
            # once, so the change waits for that edit instead of re-asking.
            planned[change] = {"hash": digest, "attempts": max_attempts, "ok": False}
            _write_planned(inst, planned)
            log(f"not planning {change}: {error}")
            continue
        except Exception as error:  # noqa: BLE001
            attempts = (record.get("attempts", 0) if record.get("hash") == digest else 0) + 1
            planned[change] = {"hash": digest, "attempts": attempts, "ok": False}
            _write_planned(inst, planned)
            giving_up = " — giving up until tasks.md changes" if attempts >= max_attempts else ""
            log(
                f"planning {change} failed ({attempts}/{max_attempts})"
                f"{giving_up} — {type(error).__name__}: {error}"
            )
            continue

        units = list(plan.units)
        before = {u.id: u for u in store.all()}
        store.upsert(units, change=change)
        dropped = [join for join in plan.joins if not _write_join(inst, store, join)]
        log(f"planned {change}: {len(units)} unit(s)")
        orphaned = _orphaned_changes(store, before)
        for other in sorted(orphaned):
            # The unit that carried this change's groups is gone, and nothing
            # else builds them: plan it again rather than leave them held by an
            # `unplanned` unit.
            log(f"{change}: {other} is planned again, the unit carrying its groups was dropped")
            planned.pop(other, None)
        if orphaned:
            _write_planned(inst, planned)
        if dropped:
            # A unit started while the plan was made. What was to be carried
            # is planned again next round, so this change is not recorded as
            # planned.
            log(f"{change}: {len(dropped)} join(s) dropped, a unit started since the plan")
            continue
        planned[change] = {"hash": digest, "attempts": 0, "ok": True}
        _write_planned(inst, planned)


def _orphaned_changes(store: UnitStore, before: dict[str, StoredUnit]) -> set[str]:
    """Changes whose groups a unit just demoted to `unplanned` was carrying."""
    return {
        member.change
        for unit in store.all()
        if unit.state == UNPLANNED and before.get(unit.id) and before[unit.id].state != UNPLANNED
        for member in unit.joined
    }


def _write_join(inst: Installation, store: UnitStore, join: Join) -> bool:
    """Apply one planned join with both branches held and both units read again.

    A branch a live process holds is a unit that has started, as one that has
    recorded a branch is: either way the join is dropped and nothing changes.
    """
    ids = [join.onto, *([join.unit] if join.unit else [])]
    try:
        branches = [branch_name(store.get(uid)) for uid in ids]
        with ExitStack() as held:
            for branch in branches:
                held.enter_context(branch_lock(branch, root=inst.state_dir / "locks"))
            estimates = store.join(join)
    except (BranchBusy, KeyError):
        return False
    if estimates is None:
        return False
    before, after = estimates
    added = after - before
    if join.unit:
        log(f"joined {join.unit} onto {join.onto} — est {before}+{added}={after}; it is removed")
    else:
        groups = ", ".join(str(n) for n in join.groups)
        taken = f"{join.change} group(s) {groups}"
        log(f"joined {taken} onto {join.onto} — est {before}+{added}={after}")
    return True


# "- [x] 1.1 ..." and "- [ ] 1.1 ..." are the same specification at different
# stages of being carried out.
CHECKBOX = re.compile(r"^(\s*-\s*\[)[ xX](\])", re.MULTILINE)


def specification(tasks: Path) -> str:
    """A change's tasks with progress stripped out.

    What a re-plan should key on is what the change *asks for*, not how much
    of it is done. The pipeline ticks these boxes as units land, and hashing
    the raw file would re-plan on every tick — with the planner then seeing
    the work marked done and proposing a graph that built no groups at all.
    """
    # `Needs:` lines too: they only add dependencies, which `link_needs`
    # applies on its own. Re-planning a change for one would be a model call
    # that can reshuffle units already built.
    text = CHECKBOX.sub(r"\1 \2", tasks.read_text())
    return "\n".join(line for line in text.splitlines() if not NEEDS_LINE.match(line.strip()))


# Units that still need a tick: being built, waiting to be, or open for review
# (whose CI, comments and merge only a poll notices). Merged and closed are
# done; failed and held wait for a person, and a tick changes nothing for them.
NEEDS_TICKS = (PLANNED, RUNNING, IN_REVIEW)


def has_work(inst: Installation, store: UnitStore) -> bool:
    """Whether a tick has anything to do: a unit in progress, a change
    whose tasks.md has not been planned in its current form, or a change with
    a satisfied unit that is ready to archive and not yet verified.

    The last is the one a poll cannot notice: a merge is found at the top of a
    tick and archived in it, but a unit ends satisfied inside the scheduling
    step, after that. A failed verification is on record, so it does not keep
    ticks busy.
    """
    units = store.all()
    if any(unit.state in NEEDS_TICKS for unit in units):
        return True
    satisfied = [u for u in units if u.state == SATISFIED]
    if satisfied:
        record = VerifyRecord(inst.state_dir / "verified.json")
        waiting = set(_unverified(inst, units, record))
        if any(m.change in waiting for u in satisfied for m in u.members()):
            return True
    planned = _planned_hashes(inst)
    for tasks in inst.tasks_files():
        record = planned.get(tasks.parent.name) or {}
        digest = hashlib.sha256(specification(tasks).encode()).hexdigest()
        if record.get("hash") != digest or not record.get("ok"):
            return True
    return False


def _planned_hashes(inst: Installation) -> dict[str, dict]:
    """What has been planned, and what failed to plan, keyed by change.

    Machine-local and safe to lose: `upsert` merges by unit id and keeps
    state, branch and PR, so a forgotten record costs one model call.
    """
    try:
        loaded = json.loads((inst.state_dir / "planned.json").read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in loaded.items() if isinstance(v, dict)}


def _write_planned(inst: Installation, records: dict[str, dict]) -> None:
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    (inst.state_dir / "planned.json").write_text(json.dumps(records, indent=2) + "\n")


def has_identity(inst: Installation, repo: str) -> bool:
    """Whether git in `repo` knows who its commits belong to.

    The effective identity, not a repo-local one: one global identity is an
    ordinary way to set a machine up, and refusing to build until it is copied
    into every checkout rejects a working configuration over a difference that
    makes none.

    What it must not do is commit with no identity at all. Git then either
    refuses outright or invents one from the login name and the hostname, and
    an unattended agent's commits end up attributed to nobody.

    A workspace whose repos belong to different accounts does still want an
    identity per repo. `abk doctor` reports which scope each one resolves
    through, so that stays visible rather than being enforced here — the
    pipeline cannot tell a deliberate single identity from a careless one.
    """
    path = inst.checkouts.get(repo)
    if path is None:
        return False

    return all(
        git(path, "config", f"user.{field}", check=False).stdout.strip()
        for field in ("email", "name")
    )


def fetch_all(inst: Installation) -> None:
    """Bring each code repo's remote refs up to date. See `units.local_ref`.

    Only remote-tracking refs move: the checkout's own branches are the
    user's, and are left exactly where they are.
    """
    for repo, path in inst.checkouts.items():
        with repo_turn(inst, repo):
            result = git(path, "fetch", "-q", "--prune", "origin", check=False)
        if result.returncode:
            why = result.stderr.strip()
            log(f"fetch of {repo} failed — building on what it last fetched: {why}")


def repo_turn(installation: Installation, repo: str) -> AbstractContextManager[None]:
    """The turn a repo's `.git` is taken by. Adding a worktree, pushing, moving
    or removing a branch all take git's own locks there, which fail rather
    than wait."""
    return file_lock(installation.state_dir / "locks" / f"repo-{repo}.lock")


class StackMoves(TypedDict):
    """What moves and cleans up after a unit that leaves the stack, merged or
    satisfied, by the names `build_dispatch` and `release_children`
    both take."""

    restack: Callable[..., None]
    remove_worktree: Callable[..., None]
    delete_branch: Callable[..., None]
    claim: Callable[[StoredUnit], AbstractContextManager[object]]
    retarget: Callable[[StoredUnit, str], None]
    rebase_cap: int | None
    resume: Callable[..., bool]


def build_stack_moves(store: UnitStore, installation: Installation) -> StackMoves:
    """The one place the merge handler and the satisfied path get what they
    move a stack with, every write to a repo's `.git` in that repo's turn, so
    the two cannot drift."""
    checkouts = installation.checkouts
    names = {path: repo for repo, path in checkouts.items()}

    def named[T](step: Callable[..., T]) -> Callable[..., T]:
        def in_turn(repo: str, *args, **kwargs) -> T:
            with repo_turn(installation, repo):
                return step(repo, *args, **kwargs)

        return in_turn

    def at_path[T](step: Callable[..., T]) -> Callable[..., T]:
        def in_turn(path: Path, *args, **kwargs) -> T:
            with repo_turn(installation, names[path]):
                return step(path, *args, **kwargs)

        return in_turn

    return {
        "restack": build_restack(
            repos=checkouts,
            store=store,
            root=installation.worktree_root,
            posts_root=installation.state_dir,
            move=at_path(resolved_move),
            push=at_path(push_with_lease),
        ),
        "remove_worktree": named(build_remove_worktree(checkouts, root=installation.worktree_root)),
        "delete_branch": named(build_delete_branch(checkouts)),
        "claim": build_claim(installation.state_dir / "locks"),
        "retarget": build_retarget(),
        "rebase_cap": installation.stack_depth_rebase_cap,
        "resume": lambda unit, kind, reason, feedback, from_person=False: (
            resume_thread(
                installation,
                unit,
                kind,
                store=store,
                reason=reason,
                feedback=feedback,
                from_person=from_person,
            )
            is not None
        ),
    }


def _dispatch(inst: Installation, store: UnitStore) -> Callable[..., bool]:
    """What each poller event is handed to, every write to a repo's `.git` in
    that repo's turn. Also how a merge the poll has not reported yet is recorded."""
    return build_dispatch(
        store,
        **build_stack_moves(store, inst),
        fetch_review=build_fetch_review(),
        fetch_checks=build_fetch_check_logs(),
        rerun_checks=build_rerun_checks(),
        # A pass polls between builds, so an event may name a unit still
        # building; the handlers leave it to a later poll. See `events`.
        waiting_path=inst.state_dir / "held-waiting.json",
        log=log,
    )


def poll_all(inst: Installation, *, store: UnitStore) -> None:
    """Ask GitHub what changed in each repo, and act on it.

    One poller per repo, each with its own recorded state, so a failure in one
    doesn't replay the other's history. The first poll of a repo records
    without dispatching — a fresh state file must not look like a hundred
    simultaneous merges.

    A pass polls while builds run, so every step here that writes to a repo's
    `.git` — deleting a branch, removing a worktree, a restack's rebase and
    push — takes the repo's turn, as the builds' own writes do. A restack's
    move holds the turn from start to finish, including the conflict
    resolver's model run when the rebase conflicts. The rebase is in progress
    in the repo's own checkout, and a build's worktree add or push must not
    land in the middle of it. So a conflicted restack keeps that repo's builds
    waiting at worktree add or push until its resolver finishes. Only the
    restack's tier 1 run happens outside the turn: it writes nothing to
    `.git`, and holding the turn through it would keep every build in the
    repo waiting on a test run as well.
    """
    checkouts = inst.checkouts

    dispatch = _dispatch(inst, store)

    labels = StateLabels(inst.forge_of, log=log)
    for repo in checkouts:
        forge, repo_id = inst.forge_of(repo)
        # The identity as one string: what `own-posts.json` has always been
        # keyed on, so an installation keeps its record of its own comments.
        slug = forges.key(repo_id)
        Poller(
            repo=slug,
            state_path=state_path(inst.state_dir, repo),
            # Bound to this repo: the poller reports a bare number, and a
            # number names a unit only together with the repo it was read from.
            dispatch=lambda event, number, repo=repo, **kwargs: dispatch(
                event, number, repo=repo, **kwargs
            ),
            list_prs=lambda forge=forge, repo_id=repo_id: forge.list_prs(repo_id),
            ignore=lambda number, slug=slug: ignored(inst.state_dir, slug, number),
            consume=lambda number, name, repo=repo: labels.consume(repo, number, name),
            log=log,
        ).poll()


class _Run:
    """How a unit's run ended, for its span and its duration: the run's status,
    or why it did not get as far as one."""

    outcome = "interrupted"


def build_unit(
    inst: Installation, unit: Unit, *, store: UnitStore, queued: spans.Mark | None = None
) -> bool:
    """`_build_unit` as a `unit` span below the tick's, with the run's duration.

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
                inst, unit, store=store, run=run, trace=telemetry.reference(span), queued=queued
            )
        except BaseException:
            telemetry.failed(span)
            raise
        finally:
            if run.outcome == "failed":
                telemetry.failed(span)
            span.set_attribute("outcome", run.outcome)
            telemetry.duration(
                "abk.unit.duration",
                time.monotonic() - started,
                repo=unit.repo,
                tier=unit.tier,
                outcome=run.outcome,
            )


def _build_unit(
    inst: Installation,
    unit: Unit,
    *,
    store: UnitStore,
    run: _Run,
    trace: str = "",
    queued: spans.Mark | None = None,
) -> bool:
    """Start the unit's thread, or resume the one a killed or paused run left,
    and run it to a wait or the end. Returns False only when the tick should stop.

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

    def say(message: str) -> None:
        # One stamp for both, so the file lines up with the journal.
        at = stamp()
        log(f"{unit.id}: {message}", at=at)
        if run_log is not None:
            run_log.emit(f"[{at}] {message}")

    def end(message: str, outcome: str) -> None:
        nonlocal ended
        ended = message
        run.outcome = outcome
        say(message)

    try:
        try:
            with ExitStack() as held:
                held.enter_context(branch_lock(branch, root=inst.state_dir / "locks"))
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
                    end("skipped, it was joined into another unit", "skipped")
                    return True
                # A unit may also be `running`: killed or paused in a node,
                # which is how its thread resumes it.
                if unit.state not in (PLANNED, RUNNING):
                    end(f"skipped, it is now {unit.state}", "skipped")
                    return True
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
                runner = build_runner(
                    unit,
                    store=store,
                    installation=inst,
                    record_merge=lambda repo, pr: _dispatch(inst, store)("merged", pr, repo=repo),
                    log=say,
                    log_reaches_run_log=True,
                )
                outcome = run_unit_thread(
                    inst, runner, unit, base=base, graph=graph, run_log=run_log
                )
        except NotImplementedError as error:
            # A toolchain profile the framework does not implement yet: not the
            # unit's fault, and nothing a retry changes. Held for a person.
            end(f"held — {error}", "held")
            store.set_state(unit.id, HELD, note=str(error), held_by=HeldBy.TOOLCHAIN)
            return True
        except Interrupted as error:
            # Left `running`, with the lock released as the `with` exits: the next
            # tick resumes its thread at the node it was in. Not failed — nothing
            # is known to be wrong.
            end(f"interrupted ({error}); the next tick resumes it", "interrupted")
            return True
        except RateLimited as error:
            # Not the unit's fault and not retried: the account is out of room, so
            # marking it failed would drop real work from the plan, and trying the
            # next unit would spend a call to be told the same thing.
            when = error.resets_at
            if when is None and runtimes.active().supports_usage_tracking:
                reading = current_usage()
                when = reading.resets_at if reading else None

            state = pause_until(
                when,
                reason=f"rate limited during {unit.id}",
                marker=_paused_marker(inst),
                kind="rate_limit",
            )
            telemetry.count("abk.usage.pauses", kind="rate_limit")
            end(f"rate limited — pausing until {state.until:%H:%M UTC}", "rate_limited")
            return False
        except BranchBusy as error:
            # Another tick is already on it. Not a failure — marking it one would
            # drop a unit that is going fine out of the plan.
            end(f"skipped, {error}", "skipped")
            return True
        except Exception as error:  # noqa: BLE001 — see the docstring.
            end(f"failed, {type(error).__name__}: {error}", "failed")
            # A rejected commit's reason is the gate's own output: on the unit's
            # record, not only in a tick log someone would have to find.
            note = str(error) if isinstance(error, CommitRejected) else ""
            try:
                store.set_state(unit.id, "failed", note=note)
            except Exception as second:  # noqa: BLE001
                say(f"could not be recorded as failed — {second}")
            return True

        end(f"{outcome.status} — {outcome.detail}", str(outcome.status))
        if outcome.status == "paused":
            telemetry.count("abk.usage.pauses", kind="usage")
            _pause_for_usage(inst, outcome.detail)
            return False
        return True
    finally:
        if run_log is not None:
            run_log.close(ended)


def _pause_for_usage(inst: Installation, reason: str) -> None:
    """Pause the pipeline for a run the usage guard stopped.

    Re-read rather than reuse the tick's reading: the guard said no after the
    units before this one ran, so the window has moved, and a resume scheduled
    from the stale figure wakes up into a full window. The guard's own answer
    to when, which counts the ramp towards the reset — not the reset itself,
    which it can be well before.
    """
    until = build_resume_at(usage=current_usage, decide=may_start_unit)()
    state = pause_until(until, reason=reason, marker=_paused_marker(inst))
    log(f"pausing until {state.until:%H:%M UTC}")


def _starting_step(inst: Installation, unit: StoredUnit) -> tuple[str, str]:
    """The step a run of this unit starts at, and the model it names: the node
    its thread is positioned at, or `implement` for a build that has none. A
    review of a rework is named apart, as it is judged by its own model; the
    steps that call no model say so."""
    where = thread_of(inst, unit.id)
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
        run_log_dir(inst.state_dir),
        unit,
        step=step,
        model=model,
        base=base,
        started=datetime.now(UTC),
        report=lambda message: log(f"{unit.id}: {message}"),
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
    return asyncio.run(_on_thread(inst, runner, unit, base=base, graph=graph, run_log=run_log))


async def _on_thread(
    inst: Installation,
    runner: UnitRunner,
    unit: Unit,
    *,
    base: str,
    graph: list[StoredUnit],
    run_log: RunLog | None,
    event: ResumeEvent | None = None,
    feedback: Callable[[], tuple[str, bool, tuple[str, ...]]] | None = None,
) -> RunOutcome:
    """Start or resume the unit's thread to its next wait, or deliver `event` to it."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
    from agent_build_kit.graph.unit import resume_unit, run_unit

    common = dict(base=base, graph=graph, run_log=run_log, tracer=telemetry.tracer())
    async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
        if event is None:
            # Under the lock `build_unit` holds; a delivery takes its own.
            return await run_unit(runner, unit, saver=saver, **common)
        return await resume_unit(
            runner,
            unit,
            saver=saver,
            event=event,
            feedback=feedback,
            locks=inst.state_dir / "locks",
            **common,
        )


class Resumed(Frozen):
    """What delivering an event to a thread did: the run's outcome, and whether
    it raised (the unit is then recorded as failed)."""

    outcome: RunOutcome
    raised: bool = False


def resume_thread(
    inst: Installation,
    unit: StoredUnit,
    kind: str,
    *,
    store: UnitStore,
    reason: str = "",
    feedback: str | Callable[[], tuple[str, bool, tuple[str, ...]]] = "",
    from_person: bool = False,
) -> Resumed | None:
    """Deliver an event to the unit's thread, which then waits for the tick.

    Nothing runs here but the wait node's store writes: the thread is left
    positioned at the node the event routes to, and the tick runs it in a slot.
    That is why no run log is opened, and the unit's link to its build's log is
    left alone.

    None when there is nothing to deliver it to — a unit with no thread, or a
    thread that has ended and takes no such event — and the caller handles the
    event as it always has. Raises `BranchBusy` when the
    event cannot be delivered now, because someone else holds the branch or the
    thread has a node to run; the caller keeps the event and delivers it again.
    """
    if not has_thread(inst, unit.id):
        return None
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.unit import NotWaiting

    # A callable is asked for the words only once the delivery can take them.
    lazy = feedback if callable(feedback) else None
    words = "" if callable(feedback) else feedback
    event = ResumeEvent(
        kind=EventKind(kind),
        reason=reason,
        feedback=words,
        from_person=from_person,
    )
    graph = store.all()
    base = base_of(unit, graph)

    def say(message: str) -> None:
        log(f"{unit.id}: {message}")

    try:
        runner = build_runner(
            unit,
            store=store,
            installation=inst,
            record_merge=lambda repo, pr: _dispatch(inst, store)("merged", pr, repo=repo),
            log=say,
        )
        outcome = asyncio.run(
            _on_thread(
                inst, runner, unit, base=base, graph=graph, run_log=None, event=event, feedback=lazy
            )
        )
    except NotWaiting as error:
        # The thread has ended: no node is running and none will route this.
        say(f"not delivered, {error}")
        return None
    except BranchBusy:
        say(f"{event.kind.value} deferred, the branch is busy or the thread has a node to run")
        raise
    except Exception as error:  # noqa: BLE001 — an event handler must not end the poll.
        detail = f"failed, {type(error).__name__}: {error}"
        try:
            store.set_state(unit.id, "failed")
        except Exception as second:  # noqa: BLE001
            say(f"could not be recorded as failed — {second}")
        say(detail)
        return Resumed(outcome=RunOutcome(status=RunStatus.FAILED, detail=detail), raised=True)
    say(f"{event.kind.value} delivered: {outcome.status} — {outcome.detail}")
    return Resumed(outcome=outcome)


# --- tags / gate / check / archive / openspec ----------------------------------------


def cmd_tags(args: argparse.Namespace, inst: Installation) -> int:
    """Validate a change's task-group tags (or every change's)."""
    from agent_build_kit.pipeline.work_graph import tasks_path

    changes = [t.parent.name for t in inst.tasks_files()] if args.all else [args.change]
    if not changes:
        # Silence reads as a failure; an empty store is a normal state.
        print(f"no changes in {inst.changes_dir}")
        return 0
    failed = 0
    for change in changes:
        path = tasks_path(change, inst.changes_dir)
        if not path.exists():
            print(f"no tasks.md for change {change!r} at {path}")
            failed += 1
            continue
        groups, errors = validate_tasks(path, repos=tuple(inst.repos))
        for error in errors:
            print(f"{path}:{error}")
        if errors:
            print(f"{len(errors)} problem(s) in {change}")
            failed += 1
            continue
        print(f"{change}: {len(groups)} task group(s), all tagged")
        for group in groups:
            print(f"  {group.number}. [{group.repo}] [{group.tier}] {group.title}")
    return 1 if failed else 0


def cmd_check(args: argparse.Namespace, inst: Installation) -> int:
    """`openspec validate --all --strict --json` on the planning repo."""
    from agent_build_kit import openspec

    result = openspec.validate(inst.root)
    print(result.stdout, end="")
    if result.returncode:
        print(result.stderr, end="")
    return result.returncode


def cmd_archive(args: argparse.Namespace, inst: Installation) -> int:
    from agent_build_kit import openspec

    print(openspec.archive(args.change, cwd=inst.root), end="")
    remove_change_logs(run_log_dir(inst.state_dir), args.change)
    return 0


def cmd_openspec(args: argparse.Namespace, inst: Installation) -> int:
    """Pass a command through to the OpenSpec CLI, in the planning repo."""
    from agent_build_kit import openspec

    result = subprocess.run([*openspec.command(), *args.args], cwd=inst.root, check=False)
    return result.returncode


def cmd_requeue(args: argparse.Namespace, inst: Installation) -> int:
    """Give a failed or held unit another go.

    Three different things, and the command says which. By default the unit
    resumes where it stopped: a unit that failed its tier 1 check because the
    toolchain was missing has its work on the branch, and redoing the agent's
    step would only spend the usage window to arrive at the same branch.
    `--rework` keeps the work and hands the agent the failure: a unit that
    failed tier 1 on real errors (a type check, a lint rule, a test) saved the
    output, but a resume at `verify` runs the check again and meets the same
    errors, without the agent ever seeing them. `--restart` throws the attempt
    away — the review rounds so far and the failure it was handed — for a
    failure that was the attempt's own, such as a build on the wrong base,
    where resuming would judge work that was never valid.

    Editing the store by hand gets this wrong: a unit's place in its build is
    in its thread, so putting it back to `planned` and nothing else leaves the
    thread where the failure stopped it.
    """
    store = store_for(inst)
    known = {unit.id: unit for unit in store.all()}
    if args.unit not in known:
        print(
            f"abk requeue: no unit {args.unit!r} (known: {', '.join(sorted(known)) or 'none'})",
            file=sys.stderr,
        )
        return 2
    state = known[args.unit].state
    if state not in (FAILED, HELD):
        print(
            f"{args.unit} is {state}; only a failed or held unit can be requeued "
            "(a running one would be built twice, an in-review one has a PR to orphan)"
        )
        return 1
    mode = "rework" if args.rework else "restart" if args.restart else "resume"
    if args.rework and not known[args.unit].feedback:
        print(
            f"{args.unit} has no saved failure to rework from; "
            "--restart starts it over, a plain requeue resumes it"
        )
        return 1
    try:
        delivered = resume_thread(inst, known[args.unit], "requeue", store=store, reason=mode)
    except BranchBusy as error:
        print(f"{args.unit} is being built ({error}); requeue it again once it has stopped")
        return 1
    if delivered:
        outcome = delivered.outcome
        print(
            f"{args.unit} thread resumed ({mode}): {outcome.status} — {outcome.detail}",
            file=sys.stderr if delivered.raised else sys.stdout,
        )
        return 1 if delivered.raised else 0
    if args.rework:
        store.set_state(args.unit, PLANNED, note="requeued: reworking from the saved failure")
        print(f"{args.unit} requeued, the agent will rework it from the failure it saved")
    elif args.restart:
        store.set_feedback(args.unit, "")
        store.set_state(args.unit, PLANNED, note="requeued: starting over")
        print(f"{args.unit} requeued, starting over from the agent's step")
    else:
        store.set_state(args.unit, PLANNED, note="requeued: resuming where it stopped")
        print(f"{args.unit} requeued, resuming where it stopped")
    return 0


def cmd_gate(args: argparse.Namespace, inst: Installation | None) -> int:
    """The push gate, for a branch in a checkout: tests-first order, clean
    and red at the tests commit."""
    from agent_build_kit import profiles
    from agent_build_kit.pipeline.check_runner import CheckCache
    from agent_build_kit.pipeline.gate import check_branch

    profile_name = args.profile
    base = args.base
    if inst is not None:
        repo = Path(args.repo).resolve()
        for name, path in inst.checkouts.items():
            if repo == path.resolve() or repo.is_relative_to(path.resolve()):
                profile_name = profile_name or inst.repo(name).profile
                # The remote's copy, as the runner builds on: the local branch of
                # that name is the user's, and nothing updates it.
                base = base or local_ref(trunk_of(name))
                break
    profile = profiles.get(profile_name or "python-uv")
    cache = CheckCache(args.cache) if args.cache else None
    problems = check_branch(Path(args.repo), base or "main", cache=cache, profile=profile)
    for problem in problems:
        print(f"✗ {problem}")
    if problems:
        print(f"\n{len(problems)} problem(s): this branch is not ready to push")
        return 1
    print("✓ tests-first: commits ordered, clean at the tests commit, and red there")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    tick = sub.add_parser("tick", help="one pass: usage, poll, plan, verify, archive, build")
    tick.add_argument("--dry-run", action="store_true", help="report without building")
    tick.add_argument(
        "--only",
        action="append",
        metavar="UNIT",
        help="build only this unit if it is ready (repeatable); the rest of the tick runs as usual",
    )
    tick.set_defaults(func=cmd_tick)

    status = sub.add_parser("status", help="what the pipeline thinks is going on")
    status.set_defaults(func=cmd_status)

    graph = sub.add_parser("graph", help="regenerate the unit graph page")
    graph.set_defaults(func=cmd_graph)

    verify = sub.add_parser(
        "verify", help="deploy a merged change and run its live tests, then archive it"
    )
    verify.add_argument("change")
    verify.set_defaults(func=cmd_verify)

    tags = sub.add_parser("tags", help="validate a change's task-group tags")
    tags.add_argument("change", nargs="?")
    tags.add_argument("--all", action="store_true", help="every change in the store")
    tags.set_defaults(func=cmd_tags)

    check = sub.add_parser("check", help="openspec validate --all --strict --json")
    check.set_defaults(func=cmd_check)

    requeue = sub.add_parser("requeue", help="give a failed or held unit another go")
    requeue.add_argument("unit", help="the unit id, e.g. add-marker/1")
    how = requeue.add_mutually_exclusive_group()
    how.add_argument(
        "--restart",
        action="store_true",
        help="start over from the agent's step and forget the failure, instead of resuming",
    )
    how.add_argument(
        "--rework",
        action="store_true",
        help="keep the work and have the agent rework it from the failure the unit saved "
        "(a failed check), instead of resuming into the same failure",
    )
    requeue.set_defaults(func=cmd_requeue)

    archive = sub.add_parser("archive", help="openspec archive <change> --yes")
    archive.add_argument("change")
    archive.set_defaults(func=cmd_archive)

    passthrough = sub.add_parser("openspec", help="run any OpenSpec command in the planning repo")
    passthrough.add_argument("args", nargs=argparse.REMAINDER)
    passthrough.set_defaults(func=cmd_openspec)

    gate = sub.add_parser("gate", help="the push gate for a unit's branch")
    gate.add_argument("--repo", type=Path, default=Path.cwd())
    gate.add_argument(
        "--base",
        default=None,
        help="branch this unit stacks on (default: the remote's copy of the repo's default branch)",
    )
    gate.add_argument("--cache", type=Path, default=None)
    gate.add_argument("--profile", default=None, help="toolchain profile (default: from abk.yaml)")
    gate.set_defaults(func=cmd_gate, needs_installation="optional")
