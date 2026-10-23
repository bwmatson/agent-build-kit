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
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import (
    Callable,
    Collection,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict

from agent_build_kit import claude_account, config, forges, profiles, runtimes, telemetry
from agent_build_kit.budget import cut_head
from agent_build_kit.cli.e2e_cmd import held_status_lines
from agent_build_kit.cli.policy_cmd import coverage_line
from agent_build_kit.cli.retire_cmd import cmd_retire
from agent_build_kit.compat_names import old_tag
from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent, UnitRun
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen, TestTier, widest_kind
from agent_build_kit.notify.build import build_notifier
from agent_build_kit.notify.reconcile import reconcile as reconcile_notifications
from agent_build_kit.notify.store import NotificationStore
from agent_build_kit.pipeline import (
    diagram,
    emergency_lane,
    environment,
    landing_intent,
    loaded_code,
    network_probe,
    retirement,
    spans,
    usage_report,
)
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    AdmissionRecord,
    Counted,
    SlotCount,
    TickCounts,
    UsageFacts,
    append_admission,
    append_counts,
    config_fingerprint,
    read_admissions,
)
from agent_build_kit.pipeline.archive import (
    _already_archived,
    archive_ready_changes,
    is_ready_to_archive,
)
from agent_build_kit.pipeline.cycles import (
    FINISHED,
    CycleDrops,
    CycleEdge,
    deadlocks,
    drop_cycle_edges,
    needs_cycle,
    path_between,
)
from agent_build_kit.pipeline.drafts import StateDrafts
from agent_build_kit.pipeline.e2e import (
    LOCK_WAIT_SETTING,
    NO_TEST_RAN,
    latest_full_output,
    lock_status_line,
    stack_lock,
)
from agent_build_kit.pipeline.e2e_holds import (
    Hold,
    held_path,
    hold_text,
    parked_holds,
    repo_holds,
    split_gates,
)
from agent_build_kit.pipeline.e2e_schedule import any_due, write_due
from agent_build_kit.pipeline.e2e_scope import product_path_warnings
from agent_build_kit.pipeline.events import (
    Restack,
    build_base_tip,
    build_claim,
    build_delete_branch,
    build_dispatch,
    build_fetch_check_logs,
    build_fetch_review,
    build_fork_point,
    build_remove_worktree,
    build_rerun_checks,
    build_restack,
    build_retarget,
    conflict_phrase,
)
from agent_build_kit.pipeline.file_lock import atomic_write_bytes, atomic_write_text, file_lock
from agent_build_kit.pipeline.flakes import flake_record
from agent_build_kit.pipeline.gate_holds import evaluate_gates, gate_status_lines
from agent_build_kit.pipeline.joins import JoinContext
from agent_build_kit.pipeline.label_sweep import sweep_finished
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.landing import land_units
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.manual_steps import (
    evaluate_manual_steps,
    manual_status_line,
    unmet_steps,
)
from agent_build_kit.pipeline.metric_records import emit_metric
from agent_build_kit.pipeline.pause import (
    Pause,
    clear_pause,
    end_network_pause,
    is_paused,
    network_marker,
    network_pause,
    pause_for,
    pause_in_force,
    pause_line,
    pause_marker,
    pause_until,
    pauses_in_force,
    record_pause,
)
from agent_build_kit.pipeline.planner import (
    GroupTooLarge,
    Pin,
    PlannerError,
    check_flagged_groups,
    in_flight_item,
    plan_kind,
    plan_round,
    promote_ancestors,
    unit_priority,
)
from agent_build_kit.pipeline.planning_repo import (
    default_branch_of,
    is_repo,
    restore_default_branch,
)
from agent_build_kit.pipeline.planning_sync import PlanningMode, planning_mode, sync_or_stop
from agent_build_kit.pipeline.pr_poller import (
    HOLD_LABEL,
    Poller,
    PrState,
    conflicts,
    recorded_checks,
    state_path,
    unmergeable,
)
from agent_build_kit.pipeline.pr_replies import build_post_replies, ignored, parse_answer
from agent_build_kit.pipeline.restack import (
    ConflictSession,
    Moved,
    checked_out_at,
    push_with_lease,
    resolved_move,
)
from agent_build_kit.pipeline.restack_lane import (
    Lane,
    Rest,
    RestackLane,
    RestackLanes,
    base_tip,
    forget_run_attempt,
    hold_if_spent,
    in_a_lane_run,
    lane_record,
    owed_units,
    record_path,
    record_run_attempt,
)
from agent_build_kit.pipeline.review_order import review_order, review_tiers
from agent_build_kit.pipeline.review_outcome_sweep import sweep_outcomes
from agent_build_kit.pipeline.review_rates import recorded_gates
from agent_build_kit.pipeline.run_log import (
    RunLog,
    e2e_output_dir,
    remove_change_logs,
    remove_old_logs,
    run_log_dir,
)
from agent_build_kit.pipeline.shell import git, has_origin
from agent_build_kit.pipeline.stack_runner import (
    GroupStep,
    PauseInfo,
    RunOutcome,
    RunStatus,
    UnitOutcome,
    UnitRunner,
    group_steps_of,
)
from agent_build_kit.pipeline.transcript import remove_change_transcripts, transcript_dir
from agent_build_kit.pipeline.ui_review import (
    ui_notes_of,
    ui_reply_writer,
    unit_of,
    unit_patch_of,
    with_ui_review,
)
from agent_build_kit.pipeline.unit_size import (
    Calibration,
    Kind,
    applied,
    calibrated,
    calibrations,
    over_ceiling,
    recent_examples,
    unit_ceiling,
)
from agent_build_kit.pipeline.unit_store import (
    PARK_BACKOFF,
    PARKED_CAUSES,
    REQUEUE_BY,
    UNPLANNED,
    Cause,
    FeedbackSource,
    GroupOwned,
    HeldBy,
    RequeueReason,
    ReworkKind,
    StoredSplitRequest,
    StoredUnit,
    UnitStore,
    awaits_release,
    backoff_remaining,
    feedback_source_of,
    guidance_excerpt,
    waiting_for,
)
from agent_build_kit.pipeline.units import (
    BUILDS_NOTHING,
    CLOSED,
    EVERY_SLOT,
    FAILED,
    HELD,
    IN_FLIGHT,
    IN_REVIEW,
    MERGED,
    PLANNED,
    REVIEWED,
    RUNNING,
    SATISFIED,
    EdgeKind,
    Join,
    Priority,
    ProjectKey,
    Unit,
    UnitState,
    base_of,
    branch_name,
    count_by_project,
    current_dependencies,
    dependency_wait,
    depth_of,
    direct_dependencies,
    edge_kind,
    effective_priority,
    emergency_start,
    failed_waiting_units,
    group_names,
    handoff_units,
    history_stamp,
    in_progress,
    in_progress_label,
    is_superseded,
    local_ref,
    merge_parents,
    parent_landed,
    parked_for_manual_step,
    parked_on_split,
    priority_note,
    project_counts,
    project_key,
    project_tag,
    ready_units,
    resolve_replaced,
    room_left,
    second_parent_wait,
    shown_dependencies,
    shown_waits,
    stack_age_source,
    start_room,
    trunk_of,
    uncounted,
    waiting_on,
    waiting_on_me,
)
from agent_build_kit.pipeline.untouched_failures import preexisting_record, preview
from agent_build_kit.pipeline.usage_allowances import (
    allowances_line,
    allowances_path,
    read_allowances,
    refresh_allowances,
)
from agent_build_kit.pipeline.usage_calls import (
    calls_path,
    derive_rate,
    interval_line,
    rate_line,
    read_calls,
)
from agent_build_kit.pipeline.usage_guard import (
    Decision,
    Interrupted,
    Limits,
    RateLimited,
    UsageReading,
    ask_before_call,
    claude_limits,
    current_cache_interval,
    current_usage,
    decide_start,
    forget_logged_failures,
    guard_off_line,
    held_estimate_line,
    held_usage,
    may_start_unit,
    on_account,
    reading_as,
    refreshed_usage,
    threshold_at,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.verdict import ReviewTier, SplitRequest
from agent_build_kit.pipeline.verdict_record import VERDICTS
from agent_build_kit.pipeline.verify import SplitHeld, Verification, VerifyRecord, verify_change
from agent_build_kit.pipeline.vocabulary import (
    WaitReason,
    effective_state,
    state_label,
    state_label_names,
)
from agent_build_kit.pipeline.wait_log import (
    DECISIONS_NAME,
    Wait,
    WaitRecorder,
    recorded_waits,
    trim_decision_log,
)
from agent_build_kit.pipeline.wiring import (
    build_close_pr,
    build_on_flake,
    build_resume_at,
    build_runner,
    build_unit_test,
    build_usage_gate,
    follow_predecessors,
    moving_onto,
    own_work_starts_after,
)
from agent_build_kit.pipeline.work_graph import (
    Need,
    TaskGroup,
    ValidationError,
    check_tags,
    cross_repo_needs_notes,
    current_tag,
    declared_projects,
    declared_split_names,
    group_needs,
    group_promotions,
    inverted_group_warnings,
    manual_runbook_warnings,
    old_test_kind_warnings,
    redundant_separate_warnings,
    retag_headings,
    specification_text,
    tasks_path,
    unrelated_parent_warnings,
    validate_tasks,
)
from agent_build_kit.pipeline.workspaces import (
    BranchBusy,
    branch_held,
    branch_lock,
    lock_holder_gone,
    worktree_path,
)
from agent_build_kit.profiles.base import ProfileUnsupported
from agent_build_kit.redaction import redact_text
from agent_build_kit.replay.review import directories as replay_directories
from agent_build_kit.replay.review import waiting as replay_waiting
from agent_build_kit.runtimes import AgentRateLimited, NetworkUnavailable, ServiceUnavailable
from agent_build_kit.serve.review import Review, ReviewStore

if TYPE_CHECKING:
    from agent_build_kit.graph.unit import Position


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(message: str, *, at: str | None = None) -> None:
    print(f"[{at or stamp()}] {redact_text(message, where='printed output')}", flush=True)


def store_for(inst: Installation) -> UnitStore:
    def refresh_graph(units: list[StoredUnit]) -> None:
        # A view, so it must never take the store write down with it.
        try:
            diagram.write_page(
                units,
                inst.graph_page,
                checks_of=recorded_checks(inst.state_dir),
                paused=parked_units(inst, units),
                gated=gated_units(inst, units),
                restacking=restacking_bases(inst),
                projects=declared_projects(inst.repos),
            )
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

    limits = inst.config.global_limits
    labels = StateLabels(inst.forge_of, log=log)
    drafts = StateDrafts(inst.forge_of, log=log)

    def follow(unit: StoredUnit, units: list[StoredUnit], opened: bool) -> None:
        labels.follow(
            unit,
            units,
            opened=opened,
            checks_of=recorded_checks(inst.state_dir),
            paused=parked_units(inst, units),
        )
        labels.follow_review(unit, inst.state_dir / VERDICTS)
        drafts.follow(unit, units, opened=opened)
        # Equal, and only on the write that counted it (from `running`), so it is named once.
        counted = len(unit.history) > 1 and unit.history[-2].get("state") == RUNNING
        if counted and unit.bounces == limits.bounce_limit and unit.state in (PLANNED, HELD):
            log(
                f"{unit.id} is looping: put back to {unit.state} {unit.bounces} times in "
                f"{limits.bounce_span_seconds}s by {unit.bounce_cause}; last note: {unit.note}"
            )

    return UnitStore(
        inst.state_dir / "units.json",
        on_write=refresh_pages,
        on_state=follow,
        bounce_span_seconds=limits.bounce_span_seconds,
    )


def _paused_marker(inst: Installation, account: claude_account.Account | None = None) -> Path:
    """The marker of `account`'s pause: the default account's, which is also the network's, when
    none is named."""
    return pause_marker(inst.state_dir, account)


def _paused_for(inst: Installation, unit: StoredUnit | Unit) -> Pause | None:
    """The pause in force for the unit's own account: its marker's, or a network outage."""
    return pause_for(inst.state_dir, claude_account.for_repo(inst.config, unit.repo))


def _refused_by_model(inst: Installation, unit: StoredUnit | Unit) -> bool:
    """Whether the model's refusal is in force for the unit's own account."""
    held = _paused_for(inst, unit)
    return held is not None and held.kind == "rate_limit"


def _pause_report(inst: Installation, pause: Pause, *, verb: str = "paused") -> str:
    """`pause_line`, naming the account and kind of a pause when the installation keeps accounts
    apart. A network pause is the whole installation's, so it names none."""
    line = pause_line(pause, verb=verb)
    if pause.kind == "network" or not (
        pause.account or claude_account.slots_per_account(inst.config)
    ):
        return line
    return f"account {pause.account or 'default'} ({pause.kind}): {line}"


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


def retry_closes(store: UnitStore, *, close_pr: Callable[[Unit, int, str], None]) -> None:
    """Close again each satisfied, retired or superseded unit's pull request that is still open,
    removing the record of those that closed."""
    for unit in store.all():
        pending = unit.close_pending
        if pending is None:
            continue
        if (
            unit.state not in (SATISFIED, UnitState.RETIRED) and not is_superseded(unit)
        ) or unit.pr != pending.pr:
            # The unit went on to something else (a requeue, say), and the pull request
            # may be the one now under review: the record is stale, not an order.
            store.set_close_pending(unit.id, None)
            continue
        try:
            close_pr(unit, pending.pr, pending.reason)
        except Exception as error:  # noqa: BLE001 - kept for the next pass
            log(f"{unit.id}: pull request #{pending.pr} still not closed — {error}")
            continue
        store.set_close_pending(unit.id, None)
        log(f"{unit.id}: pull request #{pending.pr} closed")


def retry_replies(inst: Installation, store: UnitStore, *, reply: Callable[..., str]) -> None:
    """Post again the replies a unit in review still owes its pull request, and keep in its
    thread only those the host again did not take. A unit whose branch is being worked on is
    left for the next pass."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
    from agent_build_kit.graph.unit import set_pending_replies

    async def write(unit_id: str, replies: tuple[str, ...]) -> None:
        async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
            await set_pending_replies(saver, unit_id, replies)

    for unit in store.all():
        if unit.state != IN_REVIEW or unit.pr is None or not unit.branch:
            continue
        owed = thread_of(inst, unit.id).state
        if owed is None or not owed.pending_replies:
            continue
        try:
            with branch_lock(unit.branch, root=inst.state_dir / "locks"):
                # Read again under the lock: a build may have posted them since.
                owed = thread_of(inst, unit.id).state
                if owed is None or not owed.pending_replies:
                    continue
                left = tuple(
                    rest
                    for answer in owed.pending_replies
                    if (
                        rest := reply(
                            repo=unit.repo,
                            pr=unit.pr,
                            answer_text=answer,
                            sha=owed.head,
                            branch=unit.branch,
                        )
                    )
                )
                if left != owed.pending_replies:
                    asyncio.run(write(unit.id, left))
        except BranchBusy:
            continue


def _owed_count(answers: Collection[str]) -> int:
    """The replies and summaries in the owed answers."""
    parsed = [parse_answer(answer) for answer in answers]
    return sum(len(a.replies) + bool(a.summary.strip()) for a in parsed if a)


def _retry_pending_replies(inst: Installation, store: UnitStore) -> None:
    retry_replies(
        inst,
        store,
        reply=build_post_replies(
            root=inst.state_dir,
            for_repo=inst.forge_of,
            log=log,
            ui_replies=ui_reply_writer(inst.state_dir, store),
        ),
    )


def _retry_pending_closes(inst: Installation, store: UnitStore) -> None:
    def close_pr(unit: Unit, pr: int, reason: str) -> None:
        build_close_pr(for_repo=inst.forge_of)(unit, pr, reason)

    retry_closes(store, close_pr=close_pr)


def _sweep_labels(inst: Installation, store: UnitStore) -> None:
    sweep_finished(
        store.all(),
        labels=StateLabels(inst.forge_of, log=log),
        state_dir=inst.state_dir,
        limit=inst.config.global_limits.label_sweep_per_tick,
        repo_order=list(inst.repos),
        log=log,
    )


def _sweep_outcomes(inst: Installation, store: UnitStore) -> None:
    sweep_outcomes(
        store.all(),
        verdicts=inst.state_dir / VERDICTS,
        forge_of=inst.forge_of,
        checkouts=inst.checkouts,
        trunks={name: repo.default_branch for name, repo in inst.repos.items()},
        now=datetime.now(UTC),
        log=log,
    )


def _status_reading(args: argparse.Namespace) -> UsageReading | None:
    """The reading held, or a fresh one when asked, which the interval may still refuse."""
    if getattr(args, "refresh", False):
        return refreshed_usage()
    return held_usage()


def _e2e_output(unit: StoredUnit) -> str:
    """The file holding the full output of the unit's last e2e-test run."""
    return latest_full_output(unit.feedback)[0]


def restacking_bases(inst: Installation) -> dict[str, str]:
    """The base of each unit the restack lane of a live tick holds, running or waiting."""
    return {entry["unit"]: entry["base"] for entry in lane_record(inst.state_dir)}


def _restack_lines(inst: Installation, units: list[StoredUnit]) -> list[str]:
    """`restacks: N running, M waiting`, and each unit restacking onto its base. A unit owed a
    restack that the lane does not hold yet waits too, and while a pause stands it says so."""
    held = lane_record(inst.state_dir)
    in_lane = {entry["unit"] for entry in held}
    by_id = {unit.id: unit for unit in units}
    owed = sorted(owed_units(inst, units) - in_lane)
    running = [entry for entry in held if entry["status"] == "running"]
    waiting = [entry for entry in held if entry["status"] != "running"]
    if not (running or waiting or owed):
        return []
    lines = [f"restacks: {len(running)} running, {len(waiting) + len(owed)} waiting"]
    for entry in [*running, *waiting]:
        where = f" ({unit_label(by_id[entry['unit']])})" if entry["unit"] in by_id else ""
        lines.append(f"  {entry['unit']}{where} restacking onto {entry['base']}")
    for unit_id in owed:
        unit = by_id[unit_id]
        pause = _paused_for(inst, unit)
        if pause is None or unit.cause is not Cause.RESTACK_DEFERRED:
            # Not deferred by a pause: a clean move proceeds during one.
            lines.append(f"  {unit.id} ({unit_label(unit)}) restacking onto {base_of(unit, units)}")
            continue
        verb = "usage pause" if pause.kind == "usage" else "paused"
        lines.append(f"  restack waiting: {unit.id} — {pause_line(pause, verb=verb)}")
    return lines


def _slots_line(inst: Installation, units: list[StoredUnit]) -> str | None:
    """`slots: 5/4, 1 restacking`: the occupancy over the cap, with the moved-base runs running
    in the lane. Nothing is printed when no slot is taken and no run is in the lane."""
    held = lane_record(inst.state_dir)
    restacking = {entry["unit"] for entry in held if entry["status"] == "running"}
    waiting = {entry["unit"] for entry in held} - restacking
    unheld = {
        unit.id
        for unit in units
        if unit.state == RUNNING and not branch_is_held(inst, unit.branch or branch_name(unit))
    }
    occupied = slot_occupancy(units, (), restacking, lane_waiting=waiting, idle=unheld)
    taken = sum(len(ids) for ids in occupied.values())
    if not (taken or restacking):
        return None
    cap = inst.max_concurrent_stacks * max(1, len(_unfinished_projects(units)))
    count = f", {len(restacking)} restacking" if restacking else ""
    return f"slots: {taken}/{cap}{count}"


def _whose(account: claude_account.Account) -> str:
    """Which account a status line is about, when it is not the default."""
    key = claude_account.account_key(account)
    label = f"{account.label}, " if account.label else ""
    return f" (account {label}{key})" if key else ""


def _account_usage_lines(
    args: argparse.Namespace, inst: Installation, account: claude_account.Account
) -> list[str]:
    """What `abk status` says of one account's usage: its reading judged on its own thresholds,
    the estimate, the allowances in force, the call rate and the cache interval, each from the
    account's own files and marked as its."""
    whose = _whose(account)
    lines = [_account_usage_line(args, account)]
    with on_account(account):
        if estimate := held_estimate_line():
            lines.append(estimate + whose)
        found = read_allowances(allowances_path(inst.state_dir, account))
        lines.append(allowances_line(found, claude_limits()) + whose)
        calls_file = calls_path(inst.state_dir, account)
        if calls := read_calls(calls_file):
            lines.append(rate_line(derive_rate(calls, now=datetime.now(UTC))) + whose)
        lines.append(interval_line(current_cache_interval(calls_file)) + whose)
    return lines


def _account_usage_line(args: argparse.Namespace, account: claude_account.Account) -> str:
    """The `usage:` line of one account: its reading judged on its own thresholds, and which
    account it is when it is not the default."""
    whose = _whose(account)
    with on_account(account), reading_as("cli-status"):
        reading = _status_reading(args)
        if not reading:
            return f"usage: unknown{whose}"
        age = int(reading.age.total_seconds() // 60)
        return f"usage: {_usage_line(reading)} ({reading.source}, {age}m old){whose}"


def cmd_status(args: argparse.Namespace, inst: Installation) -> int:
    """What the pipeline thinks is going on, without changing anything."""
    if off := guard_off_line():
        log(off)
    for paused in pauses_in_force(inst.state_dir):
        log(_pause_report(inst, paused))

    try:
        runtime = runtimes.active()
    except KeyError as exc:
        log(f"usage: runtime {config.runtime_name()} is not available: {exc}")
    else:
        log(coverage_line(runtime))
        if not runtime.supports_usage_tracking:
            log(f"usage: runtime {runtime.name} has no usage window")
        if runtime.supports_usage_tracking:
            for account in claude_account.in_use(inst.config):
                for line in _account_usage_lines(args, inst, account):
                    log(line)
        elif calls := read_calls(calls_path(inst.state_dir, None)):
            log(rate_line(derive_rate(calls, now=datetime.now(UTC))))

    if line := lock_status_line(inst.e2e_lock):
        log(line)
    for line in held_status_lines(inst):
        log(line)
    for line in gate_status_lines(
        inst, now=spans.clock.now(), refresh=getattr(args, "refresh", False)
    ):
        print(redact_text(line, where="printed output"), flush=True)

    for change, record in planned_hashes(inst).items():
        if record.get("waiting") in PLAN_WAITS:
            log(f"planning {change}: {_plan_state(record, inst.max_plan_attempts)}")

    for line in stale_plan_lines(inst):
        log(line)

    if config.active().review.enabled:
        gates = recorded_gates(inst.state_dir / VERDICTS, config.active().review)
        for name, gate in gates.items():
            if gate.clears:
                nameable = (
                    "" if gate.nameable else ", not nameable: no review.classes entry names it"
                )
                samples = gate.rates.samples
                log(f"review gates: {name} clears the gates ({samples} samples{nameable})")

    units = store_for(inst).all()
    if not units:
        log("no units planned")
        return 0
    recorded = environment.read_state(inst.state_dir)
    if recorded is not None:
        if recorded.healthy:
            log("environment: healthy")
        else:
            log("environment: unhealthy")
            for line in recorded.output.splitlines():
                log(f"  {line}")
    checks_of = recorded_checks(inst.state_dir)

    by_state: dict[str, int] = {}
    paused = parked_units(inst, units)
    for unit in units:
        shown = (
            unit.state
            if unit.state not in (RUNNING, IN_REVIEW)
            else effective_state(unit, units, checks_of=checks_of, paused=paused)
        )
        by_state[shown] = by_state.get(shown, 0) + 1
    log("units: " + ", ".join(f"{count} {state}" for state, count in sorted(by_state.items())))
    for name, (directory, _) in replay_directories(inst.repos, inst.checkouts).items():
        if held := len(replay_waiting(directory)):
            log(f"cassettes: {held} waiting for review in {name} (`abk replay review`)")

    for storm in flake_record(inst).storms():
        log(
            f"  flake storm: {storm.unit} — {storm.count} tests failed the first pass and "
            f"passed alone ({storm.at:%Y-%m-%d %H:%M} UTC), no fix changes"
        )

    for flaky in flake_record(inst).counts():
        times = f"{flaky.count} time{'' if flaky.count == 1 else 's'}"
        log(f"  flaky: {flaky.test} — flaked {times}, fix {flaky.change or 'not written yet'}")

    for failing in preexisting_record(inst).counts():
        times = f"{failing.count} time{'' if failing.count == 1 else 's'}"
        waiting = sum(
            1
            for unit in units
            if unit.change != failing.change
            and any(parent.change == failing.change for parent in waiting_on(unit, units))
        )
        count = f", {waiting} unit{'' if waiting == 1 else 's'} waiting" if waiting else ""
        log(
            f"  pre-existing: {failing.test} — failed on the base {times}, "
            f"fix {failing.change or 'not written yet'}{count}"
        )

    # What the last poll of each repo saw: an entry that cannot be merged is not
    # actionable, so it should not read like the others.
    conflicted: dict[str, set[int]] = {}
    conflicting: dict[str, dict[int, datetime]] = {}

    lane_use = _lane_use(inst, units)
    for key, line in _queue_full_by_project(inst, units).items():
        if _lane_has_room(inst, units, key, lane_use):
            line += "; a priority-0 unit may still start while the emergency lane has room"
        log(line)
    for line in _emergency_room_lines(inst, units, lane_use):
        log(line)
    for line in _restack_lines(inst, units):
        log(line)
    if line := _slots_line(inst, units):
        log(line)
    for line in [
        *_split_wait_lines(inst, units),
        *_manual_wait_lines(units),
        *_blocked_lines(units),
        *_retire_lines(units),
        *_failed_waiting_lines(units),
        *_wait_ended_lines(inst, units),
        *_second_parent_lines(units),
        *_replaced_lines(units),
    ]:
        log(line)

    urgency = [
        f"{unit.id} {note}"
        for unit in units
        if unit.state not in (MERGED, CLOSED) and (note := priority_note(unit, units))
    ]
    if urgency:
        log("priority: " + ", ".join(urgency))

    for line in _ready_queue_lines(inst, units):
        log(line)
    for line in _deadlocked_unit_lines(units):
        log(line)

    # Units in flight from before causes were kept: nothing reads their notes, so
    # each is requeued (`abk requeue`) or, for a reviewer's hold, held again from
    # the pull request, and the entry that follows carries a cause.
    for unit in units:
        if _is_looping(inst, unit):
            log(
                f"  looping: {unit.id} ({unit_label(unit)}) {unit.bounces} times in a row, "
                f"cause {unit.bounce_cause} — {unit.note}"
            )
    uncaused = [
        unit.id
        for unit in units
        if unit.cause is None
        and (unit.state == HELD or (unit.state == PLANNED and not unit.unstarted))
    ]
    if uncaused:
        log(f"no recorded cause: {', '.join(uncaused)}")

    for line in _deadlock_lines(units):
        log(line)

    for unit in units:
        if (
            unit.calibrated_lines is not None
            and unit.calibrated_lines != unit.estimated_lines
            and unit.state not in (MERGED, CLOSED, *BUILDS_NOTHING)
        ):
            log(
                f"  estimate: {unit.id} ({unit_label(unit)}) "
                f"estimated {unit.estimated_lines} (calibrated {unit.calibrated_lines})"
            )

    for unit in units:
        if over_ceiling(unit.actual_lines, unit):
            figure = f" of {unit_ceiling(unit)}" if config.active().review.enabled else ""
            log(
                f"  over the ceiling{figure}: {unit.id} ({unit_label(unit)}) estimated "
                f"{unit.estimated_lines}, landed {unit.actual_lines}"
            )

    for held in Leases(lease_dir(inst.state_dir)).attachments():
        owner = next((u for u in units if u.id == held.unit_id), None)
        where = f" ({unit_label(owner)})" if owner else ""
        files = f"{held.changed} file{'' if held.changed == 1 else 's'}"
        if held.stale:
            log(
                f"  attached: {held.unit_id}{where} — {files} left by a chat whose server has "
                "gone; start the server or run `abk attach release`"
            )
        else:
            log(f"  attached: {held.unit_id}{where} — a chat is open with {files} changed")

    verdicts = inst.state_dir / VERDICTS
    tiers = review_tiers(units, verdicts) if config.active().review.enabled else {}
    shown_units = review_order(units, verdicts, tiers) if tiers else units
    for unit in shown_units:
        where = unit_label(unit)
        if unit.tier == TestTier.INTEGRATION_TEST and unit.state not in (
            MERGED,
            CLOSED,
            *BUILDS_NOTHING,
        ):
            log(f"  {unit.id} ({where}) is {unit.tier}")
        if unit.state == HELD and unit.held_by == HeldBy.REVIEW and unit.pr:
            since = _conflicting(inst, unit, conflicting).get(unit.pr)
            if since is not None:
                log(f"  held: {unit.id} ({where}) #{unit.pr} — {unit.note}; a person is needed")
        if unit.state == HELD and unit.cause is Cause.DIRTY_WORKTREE:
            log(f"  parked: {unit.id} ({where}) — {unit.note}")
        step = unit.step or "an unknown step"
        if unit.state == FAILED and unit.cause is Cause.ENVIRONMENT:
            log(f"  waiting for the environment: {unit.id} ({where}) at {step} — {unit.note}")
        elif unit.state == FAILED:
            log(f"  failed: {unit.id} ({where}) at {step} — {unit.note}")
            if kept := _e2e_output(unit):
                log(f"  full e2e-test output: {unit.id} ({where}) — {kept}")
            if blocked := _blocked_by(unit, units):
                log(f"  {blocked}")
        if (left := backoff_remaining(unit, spans.clock.now())) is not None:
            log(
                f"  {waiting_for(unit)}: {unit.id} ({where}) at {step}, "
                f"{int(left.total_seconds())}s remain — {unit.note}"
            )
        if unit.state == PLANNED and (unit.cause is Cause.GATED or unit.gated_requeue is not None):
            waits = shown_waits(unit, units)
            if waits:
                merging = merge_parents(unit, waits, units, config.active().repos)
                wait = dependency_wait(waits, merging=merging)
                log(f"  {unit.id} ({where}) {wait}")
        if is_superseded(unit):
            log(f"  superseded: {unit.id} ({where}) by {', '.join(unit.superseded_by)}")
        if unit.close_pending:
            log(
                f"  close pending: {unit.id} ({where}) #{unit.close_pending.pr} is "
                "still open; closing is retried each pass"
            )
        if unit.state == IN_REVIEW:
            try:
                owed = thread_of(inst, unit.id).state
            except Exception:  # noqa: BLE001 - status reads, and must not fail on the thread store
                owed = None
            if owed and owed.pending_replies:
                log(
                    f"  unposted replies: {unit.id} ({where}) #{unit.pr or '?'} — "
                    f"{_owed_count(owed.pending_replies)} waiting for the host to take them"
                )
            if unit.repo not in conflicted:
                conflicted[unit.repo] = unmergeable(state_path(inst.state_dir, unit.repo))
            mark = " — cannot be merged" if unit.pr in conflicted[unit.repo] else ""
            since = _conflicting(inst, unit, conflicting).get(unit.pr or 0)
            if since is not None:
                if branch_is_held(inst, unit.branch or branch_name(unit)):
                    waits = "its branch is being built"
                elif _paused_for(inst, unit):
                    waits = "waiting for the usage pause to end"
                elif not unit.is_new_conflict(since) and unit.attempts_spent(
                    config.active().global_limits.max_review_rounds
                ):
                    # Unless its base has moved: a new tip starts the count again.
                    waits = "the next poll holds it for a person unless its base has moved"
                else:
                    waits = "the next poll moves it"
                phrase = conflict_phrase(unit, base_of(unit, units), since)
                mark = f" — cannot be merged ({phrase}; {waits})"
            waiting = (
                "checking"
                if effective_state(unit, units, checks_of=checks_of) == "checking"
                else "awaiting review"
            )
            ran_none = f" — {NO_TEST_RAN}" if unit.note == NO_TEST_RAN else ""
            tier = tiers.get(unit.id)
            shown_tier = f" — tier {tier.value}" if tier else ""
            log(f"  {waiting}: {unit.id} ({where}) #{unit.pr or '?'}{shown_tier}{mark}{ran_none}")
    return 0


def _conflicting(
    inst: Installation, unit: StoredUnit, cache: dict[str, dict[int, datetime]]
) -> dict[int, datetime]:
    """When each of the repo's pull requests that the last poll found conflicting began to."""
    if unit.repo not in cache:
        cache[unit.repo] = conflicts(state_path(inst.state_dir, unit.repo))
    return cache[unit.repo]


def cmd_graph(args: argparse.Namespace, inst: Installation) -> int:
    units = UnitStore(inst.state_dir / "units.json").all()
    diagram.write_page(
        units,
        inst.graph_page,
        checks_of=recorded_checks(inst.state_dir),
        paused=parked_units(inst, units),
        restacking=restacking_bases(inst),
        projects=declared_projects(inst.repos),
    )
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


class StackBusy(Exception):
    """The live stack is in use and the caller would not wait for it."""


def verify_one(
    inst: Installation, change: str, units: list, *, wait: float | None = None
) -> Verification:
    """Deploy one merged change and run its live tests — under the stack
    lock, since both touch the one live stack e2e-test also uses. Waits
    `global_limits.e2e_lock_wait_seconds` for the lock, or `wait` seconds when given,
    then raises `StackBusy`."""
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
    skipped: set[str] = set()
    for change in _unverified(inst, units, record):
        merged = _merged_ids(change, units)
        log(f"verifying {change} live: deploy, then its live-stack tests")
        try:
            outcome = verify(change, units)
        except StackBusy:
            log(f"verifying {change} skipped — the live stack is in use; tried again next round")
            skipped.add(change)
            continue
        except SplitHeld as held:
            log(f"verifying {change} skipped — {held}; tried again next round")
            skipped.add(change)
            continue
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
        # A skipped change has no verification over its current units, whatever
        # an earlier record over fewer of them says.
        last = record.get(change)
        return change not in skipped and last is not None and last.passed

    return may_archive


def _worktrees_of(inst: Installation, units: list[StoredUnit]) -> Callable[[str], list[Path]]:
    """Where each change's units are built, for clearing what killed runs left there."""
    checkouts = inst.checkouts

    def of(change: str) -> list[Path]:
        return [
            worktree_path(checkouts[unit.repo], unit.branch, inst.worktree_root)
            for unit in units
            if unit.change == change and unit.branch and unit.repo in checkouts
        ]

    return of


def cmd_verify(args: argparse.Namespace, inst: Installation) -> int:
    """Verify one change by hand — after fixing what made it fail — and
    archive it if it passes: the tick sees no work once everything merged."""
    units = store_for(inst).all()
    try:
        outcome = verify_one(inst, args.change, units)
    except SplitHeld as held:
        print(f"{args.change}: verification skipped — {held}")
        return 1
    VerifyRecord(inst.state_dir / "verified.json").put(outcome)
    if not outcome.passed:
        print(f"{args.change}: verification failed\n{outcome.detail}")
        return 1
    print(f"{args.change}: verified — {', '.join(outcome.deployed) or 'nothing to deploy'}")
    archived = archive_ready_changes(
        units,
        planning_repo=inst.root,
        may_archive=lambda change: change == args.change,
        specs_dir=inst.config.planning.specs_dir,
        run_logs=run_log_dir(inst.state_dir),
        e2e_outputs=e2e_output_dir(inst.state_dir),
        transcripts=transcript_dir(inst.state_dir),
        usage_ledger=inst.state_dir / LEDGER_NAME,
        worktrees=_worktrees_of(inst, units),
    )
    for change in archived:
        print(f"archived {change}")
    if args.change not in archived:
        reason = _not_archived_reason(args.change, units, inst)
        print(f"{args.change}: verified but not archived ({reason}; see the log)")
        return 1
    return 0


def _not_archived_reason(change: str, units: list, inst: Installation) -> str:
    """Why a verified change was not archived, from the same checks the archive makes."""
    if _already_archived(change, inst.root, inst.config.planning.specs_dir):
        return "already archived"
    if not is_ready_to_archive(change, units):
        return "not fully merged"
    if not (inst.changes_dir / change).is_dir():
        return "withdrawn: no change directory"
    return "the archive failed"


# --- the tick ---------------------------------------------------------------------------


def cmd_tick(args: argparse.Namespace, inst: Installation) -> int:
    """One pass of the loop. Safe to call at any time.

    Ordering matters in one place: the usage check comes first, so a low
    window stops the tick before it spends anything on planning.
    """
    if off := guard_off_line():
        log(off)
    forget_logged_failures()
    # Before the planning sync: it may pull the kit's own checkout, and the head recorded must
    # be the code this process imported, not what a pull brings after.
    record = None if args.dry_run else loaded_code.start_record(inst.state_dir, inst.checkouts)
    if planning_mode(inst) == PlanningMode.SEPARATE:
        if is_repo(inst.root) and not restore_default_branch(
            inst.root, default_branch_of(inst.root), log
        ):
            return 1
    elif not sync_or_stop(inst, log):
        return 1

    # First, and silently: the timer fires every few minutes whether or not
    # there is anything to do, and an idle tick should cost nothing — not a
    # usage read, not a GitHub call, not a log line each time, not a span.
    # A dry run says what the recorded failures' fix changes are even when nothing is pending.
    if args.dry_run:
        _preview_changes(inst)
        _preview_split_releases(inst, store_for(inst), getattr(args, "only", None) or ())
    if not has_work(inst, store_for(inst)):
        return 0

    if record is not None:
        loaded_code.write_record(inst.state_dir, record)
        loaded_code.running_tick(record)

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
        loaded_code.running_tick(None)
        elapsed = time.monotonic() - started
        emit_metric("duration", "abk.tick.duration", elapsed, log, outcome=tick.outcome)
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
    """What a tick does once there is work: a round, then the builds."""
    store = store_for(inst)
    log(f"configuration {config_fingerprint(inst)}")

    if args.dry_run:
        log("dry run — the environment is not synced and waiting units are not resumed")
    else:
        # Once per tick, not on a dry run: every start decided on an estimate reads the result.
        refresh_allowances(
            inst.state_dir,
            limits=claude_limits(),
            now=datetime.now(UTC),
            accounts=claude_account.in_use(inst.config),
        )
        if not environment.ensure(inst, say=log):
            tick.outcome = "environment"
            return 1
        _resume_environment_waiters(inst, store)

    # Everything else still happens in the round — polling, planning, archiving
    # — so the store stays current; only building is narrowed by `--only`. For
    # pushing one unit through when usage is tight, without a second competing
    # for it.
    only = frozenset(getattr(args, "only", None) or ())
    if only:
        log(f"--only: building nothing but {', '.join(sorted(only))}")
    # One lane for the tick, apart from the build workers: leaving the block waits for it.
    with build_restack_lane(inst, store) as lane:
        return _tick_with(args, inst, tick, store, lane, only)


def _tick_with(
    args: argparse.Namespace,
    inst: Installation,
    tick: _Tick,
    store: UnitStore,
    lane: Lane,
    only: frozenset[str],
) -> int:
    readmission = _Readmission()
    ready = run_round(
        inst,
        store,
        building=(),
        started=(),
        only=only,
        submit=True,
        refused_needs=readmission.refused,
        lane=lane,
        dry_run=args.dry_run,
    )
    if not ready:
        held = pauses_in_force(inst.state_dir)
        # As `_may_build` holds a round: when the model has refused every account a unit could
        # start on. One account's refusal beside idle accounts is an idle tick.
        refused = {each.account for each in held if each.kind == "rate_limit"}
        startable, _left_out = _startable(inst, store, only=only, spared=())
        starting = _starting_accounts(inst, startable, planning=_needs_planning(inst, store))
        if refused and all(_label_of(each) in refused for each in starting):
            tick.outcome = "paused"
            return 0
        log(_nothing_started_reason(inst, store.all(), only=only, paused=bool(held)))
        tick.outcome = "idle"
        return 0

    _log_ready(inst, store, ready, only=only)
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

    return _schedule(inst, ready, store=store, only=only, readmission=readmission, lane=lane)


def _preview_changes(inst: Installation) -> None:
    """What the fix change of each recorded pre-existing failure is, and what scheduled e2e-test
    change is due or open: written, or to be."""
    for test in dict.fromkeys(entry.test for entry in preexisting_record(inst).entries()):
        log(preview(inst, test).line)
    write_due(inst, store_for(inst), today=spans.clock.now().date(), say=log, dry_run=True)


def _resume_environment_waiters(inst: Installation, store: UnitStore) -> None:
    """Units failed because the environment could not run them go on from where they
    stopped, now that the environment is healthy; the concurrency limits apply as
    they do to any resumed unit."""
    waiting = [
        unit.id for unit in store.all() if unit.state == FAILED and unit.cause is Cause.ENVIRONMENT
    ]
    if not waiting:
        return
    log(f"environment restored: resuming {', '.join(waiting)}")
    for unit_id in waiting:
        requeue(inst, unit_id, "resume", say=lambda text, error=False: log(text))


def _step(name: str, step: Callable[..., object], *args, **kwargs) -> None:
    """Run one step of a round. One that raises is logged and the round goes on:
    the steps are independent, and each is tried again at the next round."""
    try:
        step(*args, **kwargs)
    except Exception as error:  # noqa: BLE001
        log(f"{name} failed — {type(error).__name__}: {error}")


def reduce_stored_dependencies(store: UnitStore) -> None:
    """Store the direct dependencies of every unit that lists one another of its dependencies
    reaches, through `set_dependencies`, saying what each lost. A reduced store is untouched."""
    graph = store.all()
    for unit in graph:
        direct = direct_dependencies(unit, graph)
        if direct != unit.depends_on:
            store.set_dependencies(unit.id, direct)
            removed = [dep for dep in unit.depends_on if dep not in direct]
            log(f"{unit.id}: dependencies reduced: {', '.join(removed)}")


def _evaluate_gates(inst: Installation, *, dry_run: bool) -> None:
    """Hold or release each gated split by its gate; a dry run says what it would do."""
    for action in evaluate_gates(inst, now=spans.clock.now(), dry_run=dry_run):
        if dry_run:
            verb = "would lift" if action.action == "lift" else "would hold"
            log(f"{verb}: {action.split} — {action.reason}")
        else:
            log(f"gate {action.action}: {action.split} — {action.reason}")


def evaluate_manual_waits(
    inst: Installation,
    store: UnitStore,
    *,
    dry_run: bool = False,
    in_flight: Collection[str] = (),
    slug: str = "",
) -> None:
    """Run the checks of the manual steps units wait on, with no agent call and no usage
    reading, and deliver the resume to each unit whose last step is now done. A dry run says
    what it found and changes nothing."""
    for action in evaluate_manual_steps(
        inst, store, now=spans.clock.now(), dry_run=dry_run, slug=slug
    ):
        said = f"{action.unit}: manual step {action.slug} {action.outcome}"
        log(f"{said}: {action.line}" if action.line else said)
    if dry_run:
        return
    for unit in store.all():
        if (
            unit.state != PLANNED
            or unit.cause is not Cause.MANUAL_STEP
            or not unit.manual_steps
            or unmet_steps(unit)
            or unit.id in in_flight
        ):
            continue
        names = ", ".join(step.slug for step in unit.manual_steps)
        try:
            delivered = resume_thread(
                inst,
                unit,
                "requeue",
                store=store,
                reason=f"manual step {names} done",
                requeue=RequeueReason.RESUME,
            )
        except BranchBusy:
            continue
        if delivered is None:
            store.set_state(
                unit.id, PLANNED, note=f"requeued: manual step {names} done", cause=Cause.REQUEUED
            )


def _bound_logs(inst: Installation) -> None:
    """Keep the decision log, the admission records and the unit run logs within `retention`."""
    retention = inst.config.retention
    trim_decision_log(inst.state_dir / DECISIONS_NAME, limit_mb=retention.decision_log_mb)
    trim_decision_log(inst.state_dir / ADMISSIONS_NAME, limit_mb=retention.decision_log_mb)
    remove_old_logs(
        run_log_dir(inst.state_dir),
        inst.state_dir / LEDGER_NAME,
        days=retention.unit_log_days,
        now=datetime.now(UTC),
    )


def _reconcile_notifications(inst: Installation, store: UnitStore) -> None:
    """Show the cards the stored units call for and clear the ones they no longer do."""
    config = inst.config.notifications
    notifier = build_notifier(config)
    if notifier is None:
        return
    reconcile_notifications(
        store.all(),
        store=NotificationStore(inst.state_dir / "notifications.json"),
        notifier=notifier,
        config=config,
        log=log,
        verdicts=inst.state_dir / VERDICTS if inst.config.review.enabled else None,
    )


def _plan_is_current(record: dict, digest: str, max_attempts: int) -> bool:
    """Whether a change's recorded plan stands: its `tasks.md` is as planned and the plan
    either worked or has used its attempts."""
    return record.get("hash") == digest and bool(
        record.get("ok") or record.get("attempts", 0) >= max_attempts
    )


def _plan_rests(record: dict, digest: str, max_attempts: int, now: datetime) -> bool:
    """Whether a tick leaves a change's recorded plan alone: its `tasks.md` is as planned and
    the plan worked, has used its attempts, or waits for an outage whose next try is ahead."""
    return _plan_is_current(record, digest, max_attempts) or (
        record.get("hash") == digest and _plan_waiting(record, now)
    )


def _plan_waiting(record: Mapping, now: datetime) -> bool:
    """Whether a change's recorded plan waits for an outage and its next try is ahead."""
    if not record.get("waiting"):
        return False
    try:
        return datetime.fromisoformat(record["until"]) > now
    except (KeyError, TypeError, ValueError):
        return False


def _release_network_waits(inst: Installation) -> None:
    """The network is back: every plan waiting for it is due now, whatever its next try."""
    now = spans.clock.now().isoformat()
    update_plans(
        inst,
        lambda records: {
            change: record | {"until": now}
            for change, record in records.items()
            if record.get("waiting") == "network"
        },
    )


def _needs_planning(inst: Installation, store: UnitStore) -> bool:
    """Whether some change would be planned now: planning is a model call, so a round that
    has some to do is one the usage guard has to be asked about."""
    # A unit held for its size with a round left is split by a planning call.
    rounds = config.active().review.split_rounds
    if any(_awaiting_split(u) and u.split_rounds_used < rounds for u in store.all()):
        return True
    planned = planned_hashes(inst)
    now = spans.clock.now()
    for tasks in inst.tasks_files():
        record = planned.get(tasks.parent.name) or {}
        digest = plan_digest(tasks, record.get("hash"))
        if _plan_rests(record, digest, inst.max_plan_attempts, now):
            continue
        groups, errors = _validated(inst, tasks)
        # A change whose groups are all taken is recorded with no model call.
        taken = _taken_groups(store, tasks.parent.name)
        if not errors and not (groups and taken >= {g.number for g in groups}):
            return True
    return False


def _account_decision(
    account: claude_account.Account | None, decided: dict[str | None, Decision] | None
) -> Decision:
    """The guard's decision for `account`, asked once for each account `decided` holds."""
    key = claude_account.account_key(account)
    if decided is not None and key in decided:
        return decided[key]
    decision = decide_start(read=current_usage, decide=may_start_unit, account=account)
    if decided is not None:
        decided[key] = decision
    return decision


def _start_decision(
    accounts: Sequence[claude_account.Account | None] = (None,),
    decided: dict[str | None, Decision] | None = None,
) -> Decision:
    """The guard's decision to start, under this module's names for reading and judging: a start
    on any of `accounts` (None is the account in force) is a start. When every one refuses, the
    refusal names each and waits for the earliest of their times. `decided` keeps each account's
    decision for the rest of the round."""
    refusals: list[Decision] = []
    for account in accounts:
        decision = _account_decision(account, decided)
        if decision.may_start:
            return decision
        refusals.append(decision)
    times = [each.resume_at for each in refusals if each.resume_at is not None]
    return Decision(
        may_start=False,
        reason="; ".join(each.reason for each in refusals),
        resume_at=min(times, default=None),
        resets_at=min(
            (each.resets_at for each in refusals if each.resets_at is not None), default=None
        ),
    )


def _startable(
    inst: Installation, store: UnitStore, *, only: frozenset[str], spared: Collection[str]
) -> tuple[list[StoredUnit], bool]:
    """The units that could start this round, and whether a planned unit is left out of it.

    A unit could start when it is planned or running and not left out by `--only`, a lease or a
    backoff; one in `spared` is never left out."""
    leases = Leases(lease_dir(inst.state_dir))
    now = spans.clock.now()
    startable: list[StoredUnit] = []
    left_out = False
    for unit in store.all():
        if unit.state not in (PLANNED, RUNNING):
            continue
        excluded = (
            (only and unit.id not in only)
            or leases.holder(unit.id) is not None
            or backoff_remaining(unit, now) is not None
        )
        if not excluded or unit.id in spared:
            startable.append(unit)
        else:
            left_out = left_out or unit.state == PLANNED
    return startable, left_out


def _starting_accounts(
    inst: Installation,
    startable: Collection[StoredUnit],
    *,
    planning: bool,
) -> list[claude_account.Account | None]:
    """The accounts a round's start decision is asked of: each account of a unit that could start
    (see `_startable`), and the default account when planning is due, since planning runs on it.
    The account in force when none is."""
    found: dict[str | None, claude_account.Account | None] = {}
    for unit in startable:
        account = claude_account.for_repo(inst.config, unit.repo)
        found.setdefault(claude_account.account_key(account), account)
    if planning:
        default = claude_account.Account(limits=claude_limits())
        found.setdefault(claude_account.account_key(default), default)
    return list(found.values()) or [None]


def _held_by_the_model(
    inst: Installation, store: UnitStore, pauses: Iterable[Pause], *, spared: Collection[str]
) -> Literal["rate_limit"]:
    """A round held by the model's own pauses, one for each account it cannot start on: say so,
    and read stranded units as planned."""
    for paused in pauses:
        log(_pause_report(inst, paused))
    # A pause builds nothing, so a unit no run holds should read `planned`
    # for as long as it lasts. Not otherwise: a round that goes on resumes it.
    _step("reclaiming stranded units", reclaim_stranded, inst, store, in_flight=spared)
    return "rate_limit"


def _label_of(account: claude_account.Account | None) -> str | None:
    """The label of a named account; None for the default account (and for none)."""
    return account.label if account else None


def _may_build(
    inst: Installation,
    store: UnitStore,
    *,
    spared: Collection[str],
    quiet: bool,
    only: frozenset[str] = frozenset(),
    decided: dict[str | None, Decision] | None = None,
    held: dict[str | None, Pause] | None = None,
) -> Literal["yes", "usage", "rate_limit", "idle"]:
    """The pause checks: whether this round may start builds. "usage" means the
    guard refused; "rate_limit" means the model's own pause holds every account a unit could
    start on; "idle" means every unit that could start is left out of the round, so no
    reading was asked for and no pause was written or cleared.

    The model's refusal pauses the account that was refused and no other: `held` is given the
    pause of each such account (by its label, None for the default account), so the round can
    leave those accounts' units waiting and start the rest. A network outage pauses them all.

    A pause is not a lock: the guard is asked again on every round, so a
    threshold raised by hand, or the ramp offering room before the reset,
    ends it at the next one. Only the model's own refusal is kept to its
    deadline. See `pause`. Builds in flight are never touched by it. `quiet`
    leaves out the line saying why a build may start: the tick's own round
    says it, the refreshes of a pass would repeat it.
    """
    _step("reconciling running units", reconcile_running, inst, store, in_flight=spared)
    held = {} if held is None else held
    if paused := network_pause(inst.state_dir):
        if not network_probe.control_reachable(inst):
            # Held like a usage refusal: the round polls and records, and starts and
            # plans nothing, which costs no model call.
            if not quiet:
                log(pause_line(paused))
            _step("reclaiming stranded units", reclaim_stranded, inst, store, in_flight=spared)
            return "usage"
        end_network_pause(inst.state_dir)
        _release_network_waits(inst)
        log("the network is back; resuming")

    # The usage window is Claude Code's. A runtime without one is not held by it:
    # the account's window says nothing about an on-demand agent. Its own
    # rate-limit refusal still pauses, and holds its account.
    runtime = runtimes.active()
    held.update(
        {
            each.account: each
            for each in pauses_in_force(inst.state_dir)
            if each.kind == "rate_limit"
        }
    )
    accounts: list[claude_account.Account | None] = [None]
    startable: list[StoredUnit] = []
    left_out = planning = False
    if held or runtime.supports_usage_tracking:
        startable, left_out = _startable(inst, store, only=only, spared=spared)
        planning = _needs_planning(inst, store)
        accounts = _starting_accounts(inst, startable, planning=planning)
    open_accounts = [each for each in accounts if _label_of(each) not in held]
    if not open_accounts:
        return _held_by_the_model(
            inst, store, [held[_label_of(each)] for each in accounts], spared=spared
        )

    if runtime.supports_usage_tracking:
        if left_out and not startable and not planning:
            return "idle"
        decision = _start_decision(open_accounts, decided)
        if not decision.may_start:
            # Every open account refused: each is paused on its own marker, for its own reason.
            for each in open_accounts:
                refusal = _account_decision(each, decided)
                marker = _paused_marker(inst, each)
                before = is_paused(marker)
                state = pause_until(
                    refusal.resume_at,
                    reason=refusal.reason,
                    marker=marker,
                    account=_label_of(each),
                )
                log(_pause_report(inst, state, verb="paused" if before else "pausing"))
                if not before:
                    # A new pause; the rounds that find it still in force are not more of them.
                    emit_metric("count", "abk.usage.pauses", 1, log, kind="usage")
            _step("reclaiming stranded units", reclaim_stranded, inst, store, in_flight=spared)
            return "usage"
        reason = decision.reason
    else:
        reason = f"runtime {runtime.name} has no usage window; not checking one"

    # Each account's pause ends when its own reading allows a start, not when another's does.
    for each in open_accounts:
        marker = _paused_marker(inst, each)
        before = is_paused(marker)
        if (
            before is not None
            and runtime.supports_usage_tracking
            and not _account_decision(each, decided).may_start
        ):
            continue
        # A refusal recorded while this round was deciding is kept, and holds its account.
        if refusal := clear_pause(marker):
            held[refusal.account] = refusal
        elif before:
            whose = f" (account {each.label})" if each and each.label else ""
            log(f"resuming a pause that was to last until {before.until.astimezone():%H:%M}{whose}")
    open_accounts = [each for each in open_accounts if _label_of(each) not in held]
    if not open_accounts:
        return _held_by_the_model(inst, store, held.values(), spared=spared)
    if not quiet:
        log(reason)
    return "yes"


class _Readmission:
    """What a pass has started, and how often it let a unit back in."""

    def __init__(self) -> None:
        # Each unit this pass started, with how long its history was then: what the unit
        # records after that is later, whatever the clock says.
        self.started: dict[str, int] = {}
        self.rebuilt: dict[str, int] = {}
        self.readmitted: set[str] = set()
        self.skipped: set[tuple[str, str]] = set()
        # The `Needs:` lines refused for a cycle that the pass has already logged.
        self.refused: set[tuple[str, str]] = set()

    def admit(self, units: list[StoredUnit], in_flight: set[str]) -> None:
        """A unit this pass built and that has since been put back — sent
        back by a poll, or held by its own build because its base moved — is
        due again now, not in the next pass, which cannot start until this one
        ends."""
        for unit_id in _sent_back(units, self.started, in_flight, self.skipped):
            if self.rebuilt.get(unit_id, 0) < REBUILDS_PER_PASS:
                self.started.pop(unit_id)
                self.readmitted.add(unit_id)

    def may_resume(self, unit_id: str) -> bool:
        """Whether a unit this pass built may be started again because an event
        resumed its thread. Charged like a readmission, so a pass still ends."""
        if self.rebuilt.get(unit_id, 0) >= REBUILDS_PER_PASS:
            return False
        self.readmitted.add(unit_id)
        return True

    def charge(self, ready: list[Unit]) -> None:
        """The budget is spent when a unit is started again, not when it is
        let back in: a held unit may wait several rounds on what it was held
        for, and must not run out before it can run."""
        for unit in ready:
            if unit.id in self.readmitted:
                self.readmitted.discard(unit.id)
                self.rebuilt[unit.id] = self.rebuilt.get(unit.id, 0) + 1


def run_round(
    inst: Installation,
    store: UnitStore,
    *,
    building: Collection[str],
    started: Collection[str] = (),
    only: frozenset[str],
    submit: bool,
    readmit: _Readmission | None = None,
    quiet: bool = False,
    refused_needs: set[tuple[str, str]] | None = None,
    lane: Lane | None = None,
    dry_run: bool = False,
) -> list[Unit]:
    """One round: everything a tick does before it starts builds, safe to repeat
    beside builds in flight. Returns the units to start when `submit`.

    The usage check comes first. The model's own refusal (a `rate_limit` pause)
    ends the round there. A usage refusal skips planning, which spends a model
    call, and returns no units to start; the rest of the round runs, so merges
    and comments are recorded during a usage pause. Each later step that raises is logged and the
    rest still run. `building` and `started` name the units this pass holds, so
    the reclaim and the readiness rules leave them alone; a `readmit` lets a
    sent-back unit out of what it started and carries that set itself, so
    pass one or the other; both raise `ValueError`.
    `quiet` leaves out the guard's line saying why a build may start; `dry_run` leaves the
    parked units where they are.
    """
    if readmit is not None:
        if started:
            raise ValueError("pass `started` or `readmit`, not both")
        started = readmit.started
    spared = {*building, *started}
    _step("bounding the logs", _bound_logs, inst)
    # Before anything reads a unit's dependencies: waits, bases and restacks go by direct ones.
    _step("reducing dependencies", reduce_stored_dependencies, store)
    # Before planning and before any e2e-test selection reads the held set.
    _step("evaluating split gates", _evaluate_gates, inst, dry_run=dry_run)
    _step(
        "checking manual steps",
        evaluate_manual_waits,
        inst,
        store,
        dry_run=dry_run,
        in_flight=spared,
    )
    if not dry_run:
        # No model call, so ahead of the usage guard: planning it is what the guard holds back.
        _step(
            "writing scheduled e2e-test changes",
            write_due,
            inst,
            store,
            today=spans.clock.now().date(),
            say=log,
            say_existing=False,
        )
    decided: dict[str | None, Decision] = {}
    # The accounts the model has refused, by label: their units wait while the others start.
    model_refused: dict[str | None, Pause] = {}
    may = _may_build(
        inst, store, spared=spared, quiet=quiet, only=only, decided=decided, held=model_refused
    )
    # The guard is not asked of a refused account; its admission record says why it holds.
    for label, refusal in model_refused.items():
        decided[claude_account.account_key(claude_account.resolve(inst, label))] = Decision(
            may_start=False, reason=_pause_report(inst, refusal), resume_at=refusal.until
        )
    if may == "rate_limit":
        _step("reconciling notifications", _reconcile_notifications, inst, store)
        units = store.all()
        _record_waits(
            inst,
            store,
            units,
            only,
            lambda: wait_reasons(
                inst,
                units,
                started=set(started),
                building=set(building),
                only=only,
                usage_paused=True,
            ),
        )
        return []
    # A usage refusal only withholds builds: the round still fetches and polls,
    # so merges and comments are recorded while it lasts. Planning spends a
    # model call, so it stays behind the guard.
    admitted = may == "yes"

    # Before anything is scheduled: a PR that merged since the last round frees
    # a depth slot and changes what the branches above it should sit on, so
    # planning against the pre-poll graph builds against a stale picture.
    # Before polling: a merge the poll finds restacks the units above it
    # straight away, and they must land on the trunk as it now is.
    _refresh(inst, store=store, lane=lane)
    # Once per tick, in its first round: the rounds beside builds in flight are quiet, and a
    # dry run merges nothing.
    if not quiet and not dry_run:
        _step(
            "landing", land_units, inst, store, dispatch=_dispatch(inst, store, lane=lane), say=log
        )
    _step("finishing chat commits", deliver_committed, inst, store)
    _step("creating the thread store", _create_thread_store, inst)
    # Planning runs on the default account: not while the model has refused it.
    if admitted and None not in model_refused:
        _step("planning", plan_all, inst, store=store)
        for line in stale_plan_lines(inst):
            log(line)
    _step("recording successors", record_successors, store)
    _step(
        "linking needs",
        link_needs,
        inst,
        store=store,
        reported=refused_needs,
    )
    # A split is a planning call too: not while the guard refuses planning, though a unit that
    # cannot be split is still held for a person.
    _step(
        "splitting units held for their size",
        split_held_units,
        inst,
        store,
        may_plan=admitted and None not in model_refused,
    )
    _step("promoting prerequisites", _promote, inst, store)
    _step("reclaiming stranded units", reclaim_stranded, inst, store, in_flight=spared)
    _step("following predecessors", park_dependents, inst, store)
    _step("gating sent-back units", gate_sent_back, store)
    _step("releasing gated units", release_gated, inst, store, in_flight=spared)
    _step("requeuing units whose wait ended", requeue_wait_ended, inst, store, in_flight=spared)
    if not dry_run:
        _step(
            "reworking units whose split changed",
            release_split_changed,
            inst,
            store,
            in_flight=spared,
            only=only,
        )
        _step("releasing split-held units", release_split_held, inst, store, in_flight=spared)
    _step("reconciling notifications", _reconcile_notifications, inst, store)
    units = store.all()

    def never(change: str) -> bool:
        return False

    may_archive: Callable[[str], bool] = never
    try:
        may_archive = verify_ready(
            inst, units, verify=lambda change, units: verify_one(inst, change, units, wait=0)
        )
    except Exception as error:  # noqa: BLE001
        log(f"verifying failed — {type(error).__name__}: {error}")

    def archive() -> None:
        for change in archive_ready_changes(
            units,
            planning_repo=inst.root,
            may_archive=may_archive,
            specs_dir=inst.config.planning.specs_dir,
            run_logs=run_log_dir(inst.state_dir),
            e2e_outputs=e2e_output_dir(inst.state_dir),
            transcripts=transcript_dir(inst.state_dir),
            usage_ledger=inst.state_dir / LEDGER_NAME,
            worktrees=_worktrees_of(inst, units),
        ):
            log(f"archived {change}")

    _step("archiving", archive)
    _step("closing satisfied pull requests", _retry_pending_closes, inst, store)
    _step("posting owed replies", _retry_pending_replies, inst, store)
    _step("sweeping state labels", _sweep_labels, inst, store)
    if config.active().review.enabled:
        _step("sweeping review outcomes", _sweep_outcomes, inst, store)
    if submit and may == "usage":
        units = store.all()
        _record_waits(
            inst,
            store,
            units,
            only,
            lambda: wait_reasons(
                inst,
                units,
                started=set(started),
                building=set(building),
                only=only,
                usage_paused=True,
            ),
        )
    if not submit or not (admitted or may == "idle"):
        return []

    units = store.all()
    for unit in units:
        if (left := backoff_remaining(unit, spans.clock.now())) is not None:
            log(
                f"{unit.id}: {waiting_for(unit)}, "
                f"parked at {unit.step or 'a step'}; "
                f"{int(left.total_seconds())}s remain"
            )
    if not admitted:
        _record_waits(
            inst,
            store,
            units,
            only,
            lambda: wait_reasons(
                inst,
                units,
                started=set(started),
                building=set(building),
                only=only,
            ),
        )
        return []
    in_flight = set(building)
    if readmit:
        readmit.admit(units, in_flight)
    idle = _idle_units(inst, units, in_flight)
    # A unit no run holds takes no slot while it waits; the runs in flight do, and so do the
    # moved-base runs running in the lane, never those waiting behind its cap.
    # One this pass built that an event resumed is started again, within the
    # same budget as a readmission.
    lane_running = set(lane.running) if lane else set()
    lane_waiting = set(lane.waiting) if lane else set()
    occupied = slot_occupancy(units, in_flight, lane_running, lane_waiting=lane_waiting, idle=idle)
    workers = set().union(*occupied.values())
    # The emergency lane's units take no worker of the project's own: a rework or a resume
    # is held to the workers the lane leaves. A unit in flight is in progress for the record.
    emergency_lane.prune(inst.state_dir, _with_builds_running(units, in_flight))
    in_the_lane = emergency_lane.lane_units(inst.state_dir)
    taken = count_by_project(units, lambda unit: unit.id in workers and unit.id not in in_the_lane)
    # Owed a restack, or in the lane for one: a unit whose branch the lane holds is no longer
    # owed by the branch lock's reading, and a worker started for it would find it claimed.
    owed = owed_units(inst, units) | ({*lane.running, *lane.waiting} if lane else set())

    def model_refusal(repo: str) -> Pause | None:
        """The pause of the model's refusal of the account a repo's units run on."""
        return model_refused.get(_label_of(claude_account.for_repo(inst.config, repo)))

    resumable = _within_workers(
        [
            unit
            for unit in resumable_units(inst, units, only=only, spared=in_flight, owed=owed)
            if model_refusal(unit.repo) is None
            and (readmit is None or unit.id not in started or readmit.may_resume(unit.id))
        ],
        taken,
        cap=inst.max_concurrent_stacks,
    )
    resumed = {unit.id for unit in resumable}
    evaluated, view, _excluded, for_the_lane, lane_starts = _evaluate_round(
        inst,
        units,
        started=set(started),
        building=in_flight | resumed | lane_running,
        only=only,
        # A running unit waiting behind the lane's cap holds no slot, as one no run holds does
        # not; a planned one stays as it is, owed a restack.
        idle=(idle - resumed)
        | {unit.id for unit in units if unit.id in lane_waiting and unit.state == RUNNING},
        owed=owed,
    )
    # A unit not yet started waits when its own account refuses: no worktree, branch or lease.
    stored_by_id = {unit.id: unit for unit in units}
    refused: dict[str, str] = {}
    for unit in evaluated:
        # The model's refusal holds its account's units, one already started among them.
        if (pause := model_refusal(unit.repo)) is not None:
            refused[unit.id] = _pause_report(inst, pause)
    if runtimes.active().supports_usage_tracking:
        for unit in evaluated:
            if stored_by_id[unit.id].branch or unit.id in refused:
                continue
            decision = _account_decision(claude_account.for_repo(inst.config, unit.repo), decided)
            if not decision.may_start:
                refused[unit.id] = decision.reason
    evaluated = [unit for unit in evaluated if unit.id not in refused]
    lane_starts = lane_starts - refused.keys()
    ready = [*resumable, *evaluated]
    for unit in evaluated:
        if unit.id in lane_starts:
            emergency_lane.enter(inst.state_dir, unit)
    if readmit:
        readmit.charge(ready)
    waits = _waits_in(
        inst,
        units,
        view,
        # A unit the lane is running is not waiting for a slot: it reads as it did while owed.
        startable={unit.id for unit in evaluated} | for_the_lane | lane_running,
        skipped={
            *_parked_starts(units, started),
            *in_flight,
            *resumed,
            *(unit.id for unit in ready),
        },
        only=only,
        usage_paused=False,
        refused=refused,
    )
    _record_waits(inst, store, units, only, lambda: waits)
    if not dry_run:
        _record_admissions(
            inst,
            store,
            units,
            view,
            admitted=[unit.id for unit in evaluated],
            refused=refused,
            waits=waits,
            decided=decided,
        )
    return ready


def _slot_label(slot: Hashable) -> str:
    """How a slot is named in the admission records: a project by its tag, an account by its
    label (`default` for the default account)."""
    if isinstance(slot, ProjectKey):
        return project_tag(slot.repo, slot.project)
    return str(slot) if slot else "default"


def _why_counted(unit: StoredUnit) -> str:
    """What makes a unit count as in progress: the pull request, branch or pushed commit it has,
    else its state."""
    if unit.pr is not None:
        return f"pull request {unit.pr}"
    if unit.branch:
        return f"branch {unit.branch}"
    if unit.pushed:
        return f"pushed commit {unit.pushed}"
    return f"state {unit.state}"


def _usage_facts(inst: Installation, unit: StoredUnit, decided: dict[str | None, Decision]):
    """The usage decision of the unit's own account, as the round made it. The guard is never
    asked from here: an account the round did not ask about says so."""
    if not runtimes.active().supports_usage_tracking:
        return UsageFacts(may_start=True, reason="runtime has no usage window")
    decision = decided.get(
        claude_account.account_key(claude_account.for_repo(inst.config, unit.repo))
    )
    if decision is None:
        return UsageFacts(may_start=None, reason="not asked this round")
    return UsageFacts.model_validate(decision.model_dump(include=set(UsageFacts.model_fields)))


def _record_admissions(
    inst: Installation,
    store: UnitStore,
    units: list[StoredUnit],
    view: list[Unit],
    *,
    admitted: Collection[str],
    refused: Mapping[str, str],
    waits: Mapping[str, Wait],
    decided: dict[str | None, Decision],
) -> None:
    """Write what each admission and each wait for a slot counted, the per-slot counts of a round
    that started or refused a unit, and the pause or resume of a unit its account refused. A
    record is never a round's to lose."""
    try:
        _write_admissions(
            inst,
            store,
            units,
            view,
            admitted=admitted,
            refused=refused,
            waits=waits,
            decided=decided,
        )
    except Exception as error:  # noqa: BLE001 — a record is never a pass's to lose
        log(f"the admission records are not written ({type(error).__name__}: {error})")


def _write_admissions(
    inst: Installation,
    store: UnitStore,
    units: list[StoredUnit],
    view: list[Unit],
    *,
    admitted: Collection[str],
    refused: Mapping[str, str],
    waits: Mapping[str, Wait],
    decided: dict[str | None, Decision],
) -> None:
    path = inst.state_dir / ADMISSIONS_NAME
    fingerprint = config_fingerprint(inst)
    now = spans.clock.now()
    slot_of = _slot_of(inst)
    limit_of = _slot_limit(inst)
    by_id = {unit.id: unit for unit in units}
    counting = {unit.id for unit in view if in_progress(unit, view)}
    # The units this round starts, in start order: the view is the graph before any of them.
    fresh = [uid for uid in admitted if not by_id[uid].branch]

    def counted(slot: Hashable, besides: str, started: Sequence[str]) -> tuple[Counted, ...]:
        """The units counted in `slot`: those in progress, then `started` (units this round
        has started); not `besides`."""
        return (
            *(
                Counted(id=unit.id, state=str(unit.state), why=_why_counted(unit))
                for unit in units
                if unit.id in counting and unit.id != besides and slot_of(unit) == slot
            ),
            *(
                Counted(id=uid, state=str(by_id[uid].state), why="admitted earlier in this round")
                for uid in started
                if uid not in counting and uid != besides and slot_of(by_id[uid]) == slot
            ),
        )

    last: dict[str, AdmissionRecord] = {}
    for each in read_admissions(path):
        last[each.unit] = each

    def record(
        kind: Literal["admitted", "slot", "usage"], unit: StoredUnit, started: Sequence[str]
    ) -> None:
        slot = slot_of(unit)
        found_counted = counted(slot, unit.id, started)
        usage = _usage_facts(inst, unit, decided)
        if kind == "admitted" and usage.estimate:
            # The round asked the guard naming no unit: this unit is the next start on the
            # estimate after those the guard counted and those admitted before it on the account.
            def account_of(each: StoredUnit) -> str | None:
                return claude_account.account_key(claude_account.for_repo(inst.config, each.repo))

            place = 1 + sum(1 for uid in started if account_of(by_id[uid]) == account_of(unit))
            usage = usage.model_copy(update={"estimate_starts": usage.estimate_starts + place})
        before = last.get(unit.id)
        if (
            kind == "slot"
            and before is not None
            and before.kind == "slot"
            and (before.slot, before.limit, [c.id for c in before.counted])
            == (_slot_label(slot), limit_of(slot), [c.id for c in found_counted])
        ):
            return
        append_admission(
            path,
            AdmissionRecord(
                at=now,
                kind=kind,
                unit=unit.id,
                tick=_PROCESS_TICK,
                slot=_slot_label(slot),
                limit=limit_of(slot),
                counted=found_counted,
                usage=usage,
                fingerprint=fingerprint,
            ),
        )

    for k, uid in enumerate(fresh):
        record("admitted", by_id[uid], fresh[:k])
    for uid, waited in waits.items():
        if waited.reason in (WaitReason.QUEUE_FULL, WaitReason.SLOT):
            record("slot", by_id[uid], fresh)

    if fresh or refused:
        slots = dict.fromkeys(slot_of(unit) for unit in units)
        slot_counts = {slot: counted(slot, "", fresh) for slot in slots}
        append_counts(
            path,
            TickCounts(
                at=now,
                tick=_PROCESS_TICK,
                fingerprint=fingerprint,
                slots=tuple(
                    SlotCount(
                        slot=_slot_label(slot),
                        limit=limit_of(slot),
                        ids=tuple(c.id for c in slot_counts[slot]),
                        room=room_left(limit_of(slot), len(slot_counts[slot])),
                    )
                    for slot in slots
                ),
            ),
        )

    for unit in units:
        events = [e for e in unit.history if str(e.get("event", "")).startswith("usage_")]
        latest = events[-1] if events else {}
        account = _slot_label(claude_account.for_repo(inst.config, unit.repo).label)
        if unit.id in refused:
            if latest.get("event") != "usage_pause" or latest.get("account") != account:
                store.record_event(unit.id, "usage_pause", account=account, reason=refused[unit.id])
                record("usage", unit, fresh)
        elif unit.id in admitted and latest.get("event") == "usage_pause":
            store.record_event(unit.id, "usage_resume", account=account)


def _idle_units(
    inst: Installation, units: list[StoredUnit], in_flight: Collection[str]
) -> set[str]:
    """Running units no run holds: not in flight, and their branch's lock free."""
    return {
        unit.id
        for unit in units
        if unit.state == RUNNING
        and unit.id not in in_flight
        and not branch_is_held(inst, unit.branch or branch_name(unit))
    }


def reclaim_stranded(
    inst: Installation, store: UnitStore, *, in_flight: Collection[str] = ()
) -> None:
    """Return to `planned` each unit marked `running` that no process holds
    and no thread can resume: its run was killed before it reached a point to
    resume from. One a live process holds, or with a thread, is left, and so is
    one in `in_flight`: a unit the pass has just handed to a worker, which has
    not yet taken the branch's lock."""
    for unit in store.all():
        if (
            unit.state == RUNNING
            and unit.id not in in_flight
            and not branch_is_held(inst, unit.branch or branch_name(unit))
            and not has_thread(inst, unit.id)
        ):
            store.set_state(
                unit.id,
                PLANNED,
                note="requeued: its run ended without a thread",
                cause=Cause.REQUEUED,
            )
            telemetry.count("abk.units.reclaimed")
            log(f"{unit.id}: no run holds it — planned again")


def reconcile_running(
    inst: Installation, store: UnitStore, *, in_flight: Collection[str] = ()
) -> None:
    """Fail each `running` unit whose branch lock names a process that is gone.

    Its run ended without recording an outcome, so `abk requeue` could not move
    it while it read `running`. One with a live holder is left, and so is one
    with no lock, which is reported: nothing says whether its run ever started.
    A unit in `in_flight`, or with a thread, is left and not reported: its thread
    resumes it, which is how a run killed in a node carries on."""
    for unit in store.all():
        if unit.state != RUNNING or unit.id in in_flight or has_thread(inst, unit.id):
            continue
        gone = lock_holder_gone(unit.branch or branch_name(unit), root=inst.state_dir / "locks")
        if gone is None:
            log(f"{unit.id}: running, but no lock names a run for it")
        elif gone:
            store.set_state(
                unit.id,
                FAILED,
                note="the run ended without recording its outcome",
                cause=Cause.FAILED,
            )
            log(f"{unit.id}: its run is gone — failed")


def gate_sent_back(store: UnitStore) -> None:
    """Park a unit a poll sent back for rework while a merge edge (a dependency in another
    repository, or one marked `merged`) is unmet (only those; a same-repo parent on a review
    edge is waited for by `waiting_on` alone): it is `gated`, so the readmission rule leaves it
    for the pass that finds the gate clear, instead of starting it again."""
    units = store.all()
    repos = config.active().repos
    for unit in units:
        # The cause is standing, so a replan between the send-back and here keeps it.
        if unit.state != PLANNED or unit.cause not in READMITTED_CAUSES:
            continue
        waits = [
            parent
            for parent in waiting_on(unit, units)
            if edge_kind(unit, parent, repos).kind is EdgeKind.MERGE
        ]
        if waits:
            why = dependency_wait(waits, merging=merge_parents(unit, waits, units, repos))
            store.set_state(unit.id, PLANNED, note=why, cause=Cause.GATED)
            log(f"{unit.id}: {why}")


def deliver_committed(inst: Installation, store: UnitStore) -> None:
    """Finish the delivery of every commit a chat made and a gone process did not deliver:
    the adopted event once for that commit, then the lease that recorded it is removed."""
    from agent_build_kit.pipeline import attach

    for held in Leases(lease_dir(inst.state_dir)).attachments():
        if not (held.stale and held.committed):
            continue
        if (unit := next((u for u in store.all() if u.id == held.unit_id), None)) is None:
            continue
        done = attach.finish(inst, unit, held.committed)
        log(f"{unit.id}: commit {done.commit[:9]} {'delivered' if done.delivered else 'deferred'}")


def awaiting_planning(inst: Installation, unit: StoredUnit, units: list[StoredUnit]) -> list[str]:
    """The `Needs:` lines of the unit's groups whose target is an open change
    with no planned unit yet, as `change group N`: nothing exists to wait on, so a gate
    that looked only at units would find it clear. A target that is no longer an open
    change has been archived, which is merged."""
    planned = {
        (member.change, group)
        for other in units
        if other.state not in BUILDS_NOTHING
        for member in other.members()
        for group in member.groups
    }
    waiting: list[str] = []
    for member in unit.members():
        tasks = inst.changes_dir / member.change / "tasks.md"
        if not tasks.is_file():
            continue
        for group in member.groups:
            for need in group_needs(tasks).get(group, []):
                target = inst.changes_dir / need.change / "tasks.md"
                if (need.change, need.group) not in planned and target.is_file():
                    waiting.append(f"{need.change} group {need.group}")
    return waiting


def release_gated(inst: Installation, store: UnitStore, *, in_flight: Collection[str] = ()) -> None:
    """Deliver a planned unit's saved requeue, whatever its cause, once nothing it waits
    for is left, in the mode it was requeued with."""
    units = store.all()
    for unit in units:
        if (
            unit.state != PLANNED
            or unit.gated_requeue is None
            or unit.id in in_flight
            or waiting_on(unit, units)
            or awaiting_planning(inst, unit, units)
        ):
            continue
        why = unit.gated_requeue
        mode = {
            RequeueReason.FROM_FAILURE: "rework",
            RequeueReason.RESTART: "restart",
        }.get(why, "resume")
        try:
            delivered = resume_thread(inst, unit, "requeue", store=store, reason=mode, requeue=why)
        except BranchBusy:
            continue
        if delivered is None:
            if why is RequeueReason.RESTART:
                store.set_feedback(unit.id, "")
            # One write: it records the new cause and clears the requeue with it.
            store.set_state(
                unit.id, PLANNED, note=f"requeued: gate cleared ({mode})", cause=Cause.REQUEUED
            )
        else:
            store.set_gated_requeue(unit.id, None)


def requeue_wait_ended(
    inst: Installation, store: UnitStore, *, in_flight: Collection[str] = ()
) -> None:
    """Record the units a failed unit waits on and, once its wait has ended, requeue it
    once through `requeue`'s delivery, in the mode its record gives.

    The record is cleared by the requeue, so a wait is acted on once; a unit that is not
    failed carries none. A wait that ended on a closed prerequisite leaves the unit
    failed, with `wait_ended` for the status to show."""
    setting = inst.config.global_limits.wait_end_requeue
    if setting is config.WaitEndRequeue.OFF:
        return
    units = store.all()
    by_id = {unit.id: unit for unit in units}
    for unit in units:
        if unit.state != FAILED:
            if unit.waited_on:
                store.set_waited_on(unit.id, ())
            continue
        waits = tuple(parent.id for parent in waiting_on(unit, units))
        if waits:
            if waits != unit.waited_on:
                store.set_waited_on(unit.id, waits)
            continue
        if not unit.waited_on or unit.id in in_flight:
            continue
        # A recorded unit a replan replaced stands for the units that carry its work.
        recorded = tuple(
            dict.fromkeys(uid for old in unit.waited_on for uid in resolve_replaced(old, units))
        )
        prerequisites = [by_id.get(uid) for uid in recorded]
        closed = [
            uid if parent is None else group_names([parent])
            for uid, parent in zip(recorded, prerequisites, strict=True)
            if parent is None or parent.state in (CLOSED, *BUILDS_NOTHING)
        ]
        if closed:
            store.set_wait_ended(unit.id, ", ".join(closed))
            store.set_waited_on(unit.id, ())
        elif all(parent is not None and parent.state in REVIEWED for parent in prerequisites):
            _requeue_ended_wait(inst, store, unit, [p for p in prerequisites if p is not None])
        else:
            # The `Needs:` line was dropped while the prerequisite is still open.
            store.set_waited_on(unit.id, ())


_ENVIRONMENTAL = (Cause.TOOLCHAIN, Cause.ENVIRONMENT, *PARKED_CAUSES)
WAIT_ENDED = "its wait ended"


def _wait_end_mode(unit: StoredUnit, setting: config.WaitEndRequeue) -> str:
    """The mode a unit whose wait ended is requeued in: the setting when it forces one, else
    the rule over its record. `rework` needs a saved failure or a person's note."""
    if setting is config.WaitEndRequeue.RESUME:
        return "resume"
    if setting is config.WaitEndRequeue.REWORK:
        return "rework" if unit.feedback or unit.guidance else "resume"
    checks = (FeedbackSource.UNIT_TEST, FeedbackSource.E2E)
    if unit.cause in _ENVIRONMENTAL or not unit.feedback or unit.feedback_source not in checks:
        return "resume"
    return "rework"


def _requeue_ended_wait(
    inst: Installation, store: UnitStore, unit: StoredUnit, landed: list[StoredUnit]
) -> None:
    mode = _wait_end_mode(unit, inst.config.global_limits.wait_end_requeue)
    states = {MERGED: "merged", SATISFIED: "satisfied", IN_REVIEW: "in review"}
    named = " and ".join(
        f"{group_names([parent])} is now {states[parent.state]}" for parent in landed
    )
    tick = loaded_code.current()
    if tick is not None and all(parent.state in (MERGED, SATISFIED) for parent in landed):
        named += f", loaded by tick {tick.number}"
    code = requeue(
        inst,
        unit.id,
        mode,
        say=lambda text, error=False: log(text),
        note=unit.guidance if mode == "rework" and not unit.feedback else "",
        because=f"{WAIT_ENDED} (waiting on {named})",
    )
    if code == 0:
        store.set_waited_on(unit.id, ())


def _awaiting_split(unit: StoredUnit) -> bool:
    """Whether a unit is held for its size with a split to make."""
    return unit.state == HELD and unit.held_by == HeldBy.SIZE and unit.split_request is not None


def split_held_units(inst: Installation, store: UnitStore, *, may_plan: bool = True) -> None:
    """Ask for a split of each unit held for its size, in priority order, and supersede it by the
    pieces; a round is recorded for each attempt that succeeds or fails, none for an outage.
    Without `may_plan` (the usage guard refuses planning) a unit that cannot be split is still
    held for a person, and no planner call is made."""
    units = store.all()
    held = [u for u in units if _awaiting_split(u)]
    for unit in sorted(held, key=lambda u: (effective_priority(u, units), u.id)):
        _split_one(inst, store, unit, may_plan=may_plan)


def _hold_for_a_person(store: UnitStore, unit: StoredUnit, note: str) -> None:
    """Hold a unit that was held for its size for a person, with the reason."""
    store.set_state(unit.id, HELD, note=note, held_by=HeldBy.REVIEW, cause=Cause.TOO_BIG_FOR_TIER)
    log(f"{unit.id}: {note}; held for a person")


def _cannot_split(unit: StoredUnit, units: Sequence[StoredUnit]) -> str:
    """Why a unit held for its size cannot be split, or an empty string when it can."""
    if len(unit.groups) <= 1:
        return (
            f"too big for its tier, and it holds one group, {unit.groups[0]}, which cannot be split"
        )
    if any(member.change != unit.change for member in unit.joined):
        return (
            "too big for its tier, and it carries groups of another change, "
            "which a plan of one change cannot split"
        )
    started = [u.id for u in units if unit.id in u.depends_on and u.state in _STARTED]
    if started:
        return (
            f"too big for its tier, and {', '.join(started)} is stacked on it and has started, "
            "so replacing it would orphan that branch"
        )
    return ""


def _request_of(stored: StoredSplitRequest) -> SplitRequest:
    return SplitRequest(
        earned=ReviewTier(stored.earned),
        planned=ReviewTier(stored.planned) if stored.planned else None,
        lines=stored.lines,
        ceiling=stored.ceiling,
        drivers=stored.drivers,
    )


def _pins_of(units: Sequence[StoredUnit], change: str) -> list[Pin]:
    """The pins of the change's superseded units whose pieces have not all started."""
    if not config.active().review.enabled:
        return []
    by_id = {u.id: u for u in units}

    def unstarted(unit: StoredUnit) -> bool:
        if unit.state == CLOSED and unit.superseded_by:
            return any(unstarted(by_id[uid]) for uid in unit.superseded_by if uid in by_id)
        return unit.state == PLANNED

    return [
        Pin(held=u, split=_request_of(u.split_request))
        for u in units
        if u.change == change
        and u.state == CLOSED
        and u.superseded_by
        and u.split_request
        and unstarted(u)
    ]


def _split_one(
    inst: Installation, store: UnitStore, unit: StoredUnit, *, may_plan: bool = True
) -> None:
    """Hold `unit` for a person when it cannot be split or its rounds are used, else ask for a
    split and supersede it. A branch held by a live process defers it, with no round."""
    rounds = config.active().review.split_rounds
    if unit.split_rounds_used >= rounds:
        used = (
            "`split_rounds` is 0, so it is not split"
            if rounds == 0
            else f"split {unit.split_rounds_used} of {rounds} rounds used"
        )
        _hold_for_a_person(store, unit, f"too big for its tier, and {used}")
        return
    units = store.all()
    if why := _cannot_split(unit, units):
        _hold_for_a_person(store, unit, why)
        return
    if not may_plan:
        return
    stored = unit.split_request
    assert stored is not None
    tasks = inst.changes_dir / unit.change / "tasks.md"
    task_groups, errors = _validated(inst, tasks)
    if errors:
        log(f"not splitting {unit.id}: the tags of {unit.change} are broken")
        return
    lock = branch_lock(unit.branch, root=inst.state_dir / "locks") if unit.branch else nullcontext()
    try:
        with lock:
            _plan_and_supersede(inst, store, unit, _request_of(stored), task_groups, units, rounds)
    except BranchBusy as error:
        log(f"splitting {unit.id} is waiting for its branch, no round used — {error}")


def _plan_and_supersede(
    inst: Installation,
    store: UnitStore,
    unit: StoredUnit,
    request: SplitRequest,
    task_groups: list[TaskGroup],
    units: Sequence[StoredUnit],
    rounds: int,
) -> None:
    tasks = inst.changes_dir / unit.change / "tasks.md"
    try:
        plan = plan_round(
            changes={unit.change: tasks.read_text()},
            in_flight=_plan_context(units, unit.change),
            groups=task_groups,
            known={u.id for u in units},
            split=request,
            held=unit,
        )
        store.set_split_rounds_used(unit.id, unit.split_rounds_used + 1)
        store.supersede(unit.id, plan.units)
    except GroupTooLarge as error:
        _hold_for_a_person(store, unit, str(error))
        return
    except Exception as error:  # noqa: BLE001
        if _plan_wait(inst, error, {}) is not None:
            log(f"splitting {unit.id} is waiting for an outage, no round used — {error}")
            return
        used = unit.split_rounds_used + 1
        store.set_split_rounds_used(unit.id, used)
        log(
            f"splitting {unit.id} failed ({used} of {rounds} rounds used) — "
            f"{type(error).__name__}: {error}"
        )
        return
    log(f"split {unit.id} into {', '.join(piece.id for piece in plan.units)}")


def release_split_held(
    inst: Installation, store: UnitStore, *, in_flight: Collection[str] = ()
) -> None:
    """Deliver the resume a unit parked for held e2e-test splits was waiting for, once none of
    the splits it waits on is held. Reads the state file and the configuration alone; a gate
    is never asked. The delivery ends the park, so a unit is released once per hold."""
    for unit in _releasable_split_units(inst, store.all(), in_flight):
        try:
            delivered = resume_thread(
                inst,
                unit,
                "requeue",
                store=store,
                reason="resume",
                requeue=RequeueReason.RESUME,
            )
        except BranchBusy:
            continue
        if delivered is None:
            store.set_state(
                unit.id,
                PLANNED,
                note="requeued: the held e2e-test splits are usable",
                cause=Cause.REQUEUED,
            )


class SplitChange(Frozen):
    """A parked unit whose group's `Split:` now says another split than it is stored in."""

    unit: StoredUnit
    group: int
    new: str
    # Why the new split is held for the unit's repo, None when it is not.
    hold: Hold | None = None

    @property
    def reason(self) -> str:
        return f"its group's Split changed from {self.unit.split} to {self.new}"


def split_changes(
    inst: Installation,
    units: Sequence[StoredUnit],
    in_flight: Collection[str] = (),
    only: Collection[str] = (),
) -> list[SplitChange]:
    """The parked units (planned, cause `split_held`, with parked splits, not in flight) whose
    groups, as `tasks.md` reads now, are all in one split that is not the one the unit is stored
    in and not one it is parked on. A unit whose groups do not read as one split, or whose tasks
    file is refused or lacks a group, is left out. With `only`, a unit is read only when it or its
    change is named."""
    found = []
    for unit in units:
        if (
            unit.state != PLANNED
            or unit.cause is not Cause.SPLIT_HELD
            or not unit.parked_splits
            or unit.id in in_flight
            or unit.repo not in inst.config.repos
            or (only and unit.id not in only and unit.change not in only)
        ):
            continue
        groups: list[TaskGroup] = []
        for member in unit.members():
            tasks = inst.changes_dir / member.change / "tasks.md"
            if not tasks.is_file():
                break
            read, errors = _validated(inst, tasks)
            by_number = {g.number: g for g in read}
            if errors or any(number not in by_number for number in member.groups):
                break
            groups += [by_number[number] for number in member.groups]
        else:
            splits = {g.split for g in groups}
            if len(splits) != 1:
                continue
            (new,) = splits
            if new == unit.split or new in unit.parked_splits:
                continue
            held = repo_holds(inst.config, inst.config.repos[unit.repo], inst.state_dir).held
            found.append(
                SplitChange(unit=unit, group=groups[0].number, new=new, hold=held.get(new))
            )
    return found


def release_split_changed(
    inst: Installation,
    store: UnitStore,
    *,
    in_flight: Collection[str] = (),
    only: Collection[str] = (),
) -> None:
    """Rework, once, each parked unit whose group's `Split:` changed away from its park, unless
    the new split is held, when it stays parked until a pass finds that released. The rework is
    delivered first and the park cleared after, so a delivery that is refused changes nothing."""
    for change in split_changes(inst, store.all(), in_flight, only):
        unit = change.unit
        if change.hold is not None:
            continue
        note = (
            f"Automatic note: group {change.group}'s Split changed from {unit.split} to "
            f"{change.new} and its task text changed with it. Read group {change.group}'s tasks "
            f"in tasks.md again and apply them, including converting the tests that ran in "
            f"{unit.split}. The tasks are read again from the file."
        )
        try:
            delivered = resume_thread(
                inst,
                unit,
                "requeue",
                store=store,
                reason=change.reason,
                requeue=RequeueReason.FROM_FAILURE,
                guidance=note,
            )
        except BranchBusy:
            continue
        if delivered is None:
            store.set_guidance(unit.id, note)
            store.set_state(
                unit.id, PLANNED, note=f"requeued: {change.reason}", cause=Cause.REQUEUED
            )
        store.set_parked(unit.id)
        store.set_split(unit.id, change.new)
        log(f"reworking {unit.id} ({unit_label(unit)}): {change.reason}")


def _releasable_split_units(
    inst: Installation, units: Sequence[StoredUnit], in_flight: Collection[str] = ()
) -> list[StoredUnit]:
    """The units parked for held e2e-test splits none of which is held now."""
    # The cause is standing, so a replan carries it and this reads the same after one.
    moved = {change.unit.id for change in split_changes(inst, units)}
    return [
        unit
        for unit in units
        if unit.state == PLANNED
        and unit.cause is Cause.SPLIT_HELD
        and unit.id not in in_flight
        and not parked_holds(inst.config, inst.state_dir, unit)
        # A unit whose group moved to another split is reworked, not resumed onto its old tests.
        and unit.id not in moved
    ]


def gated_units(inst: Installation, units: Sequence[StoredUnit]) -> frozenset[str]:
    """The ids of the units a held e2e-test split keeps from starting."""
    return frozenset(split_gates(inst.config, inst.state_dir, units))


def _split_wait_lines(inst: Installation, units: Sequence[StoredUnit]) -> list[str]:
    """One line for each unit parked for a held e2e-test split, or kept from starting by one:
    which, why and until when; a unit whose split was released and has not started yet says so."""
    lines = []
    moved = {change.unit.id: change for change in split_changes(inst, units)}
    gates = split_gates(inst.config, inst.state_dir, units)
    recorded = recorded_waits(inst.state_dir / DECISIONS_NAME)
    for unit in units:
        if (gate := gates.get(unit.id)) is not None:
            why = hold_text(gate)
        elif (
            unit.unstarted
            and unit.id in recorded
            and recorded[unit.id][0].reason is WaitReason.SPLIT
        ):
            why = "released, starts this round"
        else:
            continue
        lines.append(
            f"  waiting for e2e-test split {unit.split}: {unit.id} ({unit_label(unit)}) — {why}"
        )
    for unit in units:
        if not parked_on_split(unit):
            continue
        names = ", ".join(unit.parked_splits)
        why = "; ".join(
            hold_text(hold) for hold in parked_holds(inst.config, inst.state_dir, unit).values()
        )
        if unit.id in moved:
            change = moved[unit.id]
            why = (
                f"its group now says Split {change.new} (held: {hold_text(change.hold)}), "
                "reworks when it is released"
                if change.hold
                else f"its group now says Split {change.new}, reworks this round"
            )
        dropped = unit.state == UnitState.UNPLANNED
        label = "unplanned, parked on" if dropped else "waiting for"
        released = (
            "released, left alone: the plan no longer has it"
            if dropped
            else "released, resumes this round"
        )
        lines.append(
            f"  {label} e2e-test split {names}: {unit.id} ({unit_label(unit)})"
            + (f" — {why}" if why else f" — {released}")
        )
    return lines


def _manual_wait_lines(units: Sequence[StoredUnit]) -> list[str]:
    """One line for each manual step a planned unit waits on: the last line of its check and
    where the runbook is."""
    return [
        f"  {unit.id}: {manual_status_line(step)}"
        for unit in units
        if unit.state == PLANNED
        for step in unmet_steps(unit)
    ]


def _preview_split_releases(
    inst: Installation, store: UnitStore, only: Collection[str] = ()
) -> None:
    """A dry run's account of the parked units the next round would release."""
    for unit in _releasable_split_units(inst, store.all()):
        log(
            f"would release {unit.id} ({unit_label(unit)}): "
            "the e2e-test splits it waits on are usable"
        )
    for change in split_changes(inst, store.all(), only=only):
        if change.hold is None:
            log(f"would rework {change.unit.id} ({unit_label(change.unit)}): {change.reason}")


def resumable_units(
    inst: Installation,
    units: list[StoredUnit],
    *,
    only: frozenset[str],
    spared: Collection[str] = (),
    owed: Collection[str] | None = None,
) -> list[Unit]:
    """The units whose thread a run left partway: killed in a node, or
    interrupted for the usage window, which the guard let this tick through.
    They are `running`, but hold no slot until the round starts them; a thread
    waiting for review or a person is not here, and holds none. `spared` names
    the units a run is in flight on. A unit whose lease is held waits for its release."""
    leases = Leases(lease_dir(inst.state_dir))
    # A unit owed a restack is moved by the lane first; a worker would only wait for it.
    owed = owed_units(inst, units) if owed is None else owed
    return [
        unit
        for unit in units
        if unit.state == RUNNING
        and unit.id not in owed
        and (not only or unit.id in only)
        and unit.id not in spared
        and leases.holder(unit.id) is None
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
    idle: Collection[str] = (),
) -> list[Unit]:
    """What this pass may start now: `_evaluate_round` without the view it chose from."""
    ready, _view, _excluded, _for_the_lane, _emergency = _evaluate_round(
        inst,
        units,
        started=started,
        building=building,
        only=only,
        enforce_limit=enforce_limit,
        max_concurrent=max_concurrent,
        idle=idle,
    )
    return ready


def _evaluate_round(
    inst: Installation,
    units: list[StoredUnit],
    *,
    started: set[str],
    building: set[str],
    only: frozenset[str],
    enforce_limit: bool = True,
    max_concurrent: int | None = None,
    idle: Collection[str] = (),
    owed: Collection[str] | None = None,
    emergency_extra: int | None = None,
) -> tuple[list[Unit], list[Unit], frozenset[str], frozenset[str], frozenset[str]]:
    """What this pass may start now, the graph it chose from, the units it left out, the
    planned units owed a restack, which wait for the lane's move and for nothing else, and
    those of the starts that are the emergency lane's (`emergency_extra`, the project
    setting when not given): a priority-0 unit started past the places and the workers,
    which the worker slice does not hold to them.

    A unit owed a restack is moved by the lane before a worker builds it, so it is never
    in what may start. It is left in the graph as it is, so every count and every wait
    reason is the one the existing rules give; while it waits it takes no build slot, and
    once the lane runs it, the caller passes it in `building` and it counts toward the occupancy.

    The units left out are those already started this pass, outside `--only`,
    held by a lease, awaiting a requeue or in a backoff: they give no priority
    to what they wait on.

    `ready_units` decides from the stored state alone, which lags the pass: a
    unit just handed to the pool is still `planned` until its build marks it
    `running`, and one whose build ended held is `planned` again. So the
    graph it sees counts every build in flight as running — keeping the
    concurrency cap and blocking its dependents until it finishes — and shows
    what this pass has already started, or `--only` excludes, as held. The
    answer is filtered again too: never handing a unit out twice is what
    guarantees the pass ends. `idle` names running units no run holds, which
    take no slot: they show as held, still blocking their dependents.
    """
    view: list[Unit] = []
    excluded: set[str] = set()
    now = spans.clock.now()
    leases = Leases(lease_dir(inst.state_dir))
    owed = owed_units(inst, units) if owed is None else owed
    gates = split_gates(inst.config, inst.state_dir, units)
    for unit in units:
        if unit.id in building:
            unit = unit.model_copy(update={"state": RUNNING})
        elif unit.id in idle:
            unit = unit.model_copy(update={"state": HELD})
        elif unit.state == PLANNED and (
            unit.id in started
            or (only and unit.id not in only)
            # Someone is chatting with it: it goes back to the tick when the lease is released.
            or leases.holder(unit.id) is not None
            # A requeue is still to be delivered to its thread, or its e2e tests wait for a
            # runtime: starting the unit as a planned build would drop the mode it was
            # requeued with, or build it all again.
            or awaits_release(unit)
            # Parked for the host being unavailable, and its backoff is not over.
            or backoff_remaining(unit, now) is not None
            # Its e2e-test split is held, and nothing exists yet that a hold could disturb.
            or unit.id in gates
        ):
            unit = unit.model_copy(update={"state": HELD})
            excluded.add(unit.id)
        view.append(unit)
    cap = max_concurrent or inst.max_concurrent_stacks
    for_the_lane = {unit.id for unit in view if unit.state == PLANNED and unit.id in owed}
    # Room for the owed units too, so one that is passed over does not take a slot from another:
    # a project's owed units add to its own cap, and the slice below holds the others to theirs.
    owed_by = count_by_project(view, lambda unit: unit.id in for_the_lane)
    extra = inst.emergency_extra if emergency_extra is None else emergency_extra
    lane = emergency_lane.lane_units(inst.state_dir)

    def ready_with(extra: int) -> list[Unit]:
        return ready_units(
            view,
            max_concurrent=cap,
            extra_workers=owed_by,
            depth_cap=inst.stack_depth_build_cap,
            max_units_in_progress=inst.max_units_in_progress if enforce_limit else None,
            slot_of=_slot_of(inst),
            slot_limit=_slot_limit(inst),
            excluded=excluded,
            emergency_extra=extra,
            in_lane=lane,
        )

    ready = ready_with(extra)
    # What the lane adds to the starts the normal limits give; only a unit that may use it can.
    in_the_lane: frozenset[str] = frozenset()
    if any(emergency_start(unit, view, excluded) for unit in ready):
        normal = {unit.id for unit in ready_with(0)}
        in_the_lane = frozenset(unit.id for unit in ready if unit.id not in normal)
    # The lane's units take no worker of the project's own, as in `ready_units`.
    running = count_by_project(view, lambda unit: unit.state == RUNNING and unit.id not in lane)
    startable = _within_workers(
        [unit for unit in ready if unit.id not in for_the_lane],
        running,
        cap=cap,
        in_the_lane=in_the_lane,
    )
    return (
        [unit for unit in startable if unit.id not in started],
        view,
        frozenset(excluded),
        frozenset(for_the_lane),
        in_the_lane,
    )


def _unfinished_projects(units: Iterable[Unit]) -> set[ProjectKey]:
    """The projects with a unit not yet finished."""
    return {project_key(unit) for unit in units if unit.state not in FINISHED}


def _within_workers[U: Unit](
    units: list[U],
    taken: Mapping[ProjectKey, int],
    *,
    cap: int,
    in_the_lane: Collection[str] = (),
) -> list[U]:
    """The leading units that fit the free workers of their own project, in order: `cap`
    workers each, less those in `taken`. A unit in `in_the_lane` (`_evaluate_round`) is
    admitted whatever the workers and takes none."""
    chosen: list[U] = []
    added: dict[ProjectKey, int] = {}
    for unit in units:
        key = project_key(unit)
        if unit.id in in_the_lane:
            chosen.append(unit)
        elif taken.get(key, 0) + added.get(key, 0) < cap:
            added[key] = added.get(key, 0) + 1
            chosen.append(unit)
    return chosen


def slot_occupancy(
    units: Iterable[StoredUnit],
    building: Collection[str],
    lane_running: Collection[str],
    *,
    lane_waiting: Collection[str] = (),
    idle: Collection[str] = (),
) -> dict[ProjectKey, set[str]]:
    """The unit ids that occupy build slots in each project, each id once: the builds in
    flight, the moved-base runs running in the lane, and the units stored `running` that no
    run is shown to have left (`idle`: no run holds them) and that do not wait behind the
    lane's cap (`lane_waiting`). Every count of build slots reads it."""
    ids = {*building, *lane_running}
    skipped = {*idle, *lane_waiting}
    occupied: dict[ProjectKey, set[str]] = {}
    for unit in units:
        if unit.id in ids or (unit.state == RUNNING and unit.id not in skipped):
            occupied.setdefault(project_key(unit), set()).add(unit.id)
    return occupied


def unit_label(unit: Unit) -> str:
    """How the status names a unit's place: its repo, and `repo/project` for a project beside
    the root of a repo."""
    return project_tag(unit.repo, unit.project)


def _slot_of(inst: Installation) -> Callable[[Unit], Hashable]:
    """What a unit's place in progress is counted under: its account's label (None for the
    default account) when the installation uses accounts, else its project."""
    if not claude_account.slots_per_account(inst.config):
        return project_key
    return lambda unit: claude_account.for_repo(inst.config, unit.repo).label


def _slot_limit(inst: Installation) -> Callable[[Hashable], int]:
    """The units in progress one slot of `_slot_of` allows: an account's own limit, else the
    project limit."""
    if not claude_account.slots_per_account(inst.config):
        return lambda _slot: inst.max_units_in_progress

    def limit(label: Hashable) -> int:
        named = claude_account.resolve(inst, label if isinstance(label, str) else None)
        return named.max_units_in_progress or inst.max_units_in_progress

    return limit


def _lane_has_room(
    inst: Installation,
    units: list[StoredUnit],
    slot: Hashable,
    lane_use: dict[ProjectKey, list[StoredUnit]],
) -> bool:
    """Whether the emergency lane of a project in `slot` has room: of the project itself, or of
    any project whose units are counted in the account `slot`."""
    slot_of = _slot_of(inst)
    projects = {project_key(u) for u in units if slot_of(u) == slot}
    return any(len(lane_use.get(project, ())) < inst.emergency_extra for project in projects)


def _slots_capacity(inst: Installation, units: list[StoredUnit], live: set[ProjectKey]) -> int:
    """The units in progress the gate allows in all: each live project's limit, or each account in
    use's own limit when units are counted per account."""
    slot_of = _slot_of(inst)
    if slot_of is project_key:
        return inst.max_units_in_progress * len(live)
    slots = {slot_of(unit) for unit in units if project_key(unit) in live}
    return sum(_slot_limit(inst)(slot) for slot in slots)


def _slot_name(slot: Hashable, units: list[StoredUnit]) -> str:
    """How a full slot is named in the status: a project by its tag, an account by its label."""
    if isinstance(slot, ProjectKey):
        return unit_label(next(u for u in units if project_key(u) == slot))
    return f"account {slot}" if slot else "default account"


def _slot_order(slot: Hashable) -> tuple[str, str]:
    if isinstance(slot, ProjectKey):
        return (slot.repo, slot.project)
    return (str(slot or ""), "")


def _queue_full_by_project(inst: Installation, units: list[StoredUnit]) -> dict[Hashable, str]:
    """One line for each project (or account, when the installation uses accounts) at its limit
    of units in progress, with its own blocked and failed-waiting units; the slot is named when
    the workspace has more than one."""
    slot_of = _slot_of(inst)
    parked = parked_units(inst, units)
    named = len(_live_projects(inst, units)) > 1 or slot_of is not project_key
    lines: dict[Hashable, str] = {}
    for key in sorted(project_counts(units, slot_of), key=_slot_order):
        limit = _slot_limit(inst)(key)
        if start_room(units, limit, key, slot_of):
            continue
        held = [unit for unit in units if in_progress(unit, units) and slot_of(unit) == key]
        by_label: dict[str, int] = {}
        for unit in held:
            label = in_progress_label(unit, parked=parked)
            by_label[label] = by_label.get(label, 0) + 1
        states = ", ".join(f"{count} {label}" for label, count in sorted(by_label.items()))
        name = f"{_slot_name(key, units)}: " if named else ""
        line = f"queue is full: {name}{len(held)} units in progress, limit {limit} ({states})"
        waiting = _blocked_lines(units, key, slot_of)
        if waiting:
            line += f"; {len(waiting)} blocked not counted"
        if failed := [u for u in failed_waiting_units(units) if slot_of(u) == key]:
            line += f"; {len(failed)} failed waiting not counted"
        lines[key] = line
    return lines


def _with_builds_running(units: list[StoredUnit], in_flight: Collection[str]) -> list[StoredUnit]:
    """`units` with each build in flight shown as running, as the stored state lags the pass."""
    return [
        unit.model_copy(update={"state": RUNNING}) if unit.id in in_flight else unit
        for unit in units
    ]


def _lane_use(inst: Installation, units: list[StoredUnit]) -> dict[ProjectKey, list[StoredUnit]]:
    """The units of each project that use its emergency lane: recorded in it and in progress."""
    using: dict[ProjectKey, list[StoredUnit]] = {}
    for unit in emergency_lane.users(inst.state_dir, units):
        using.setdefault(project_key(unit), []).append(unit)
    return using


def _emergency_room_lines(
    inst: Installation, units: list[StoredUnit], lane_use: dict[ProjectKey, list[StoredUnit]]
) -> list[str]:
    """One line for each project whose emergency lane is in use, naming its units; the project
    is named when the workspace has more than one."""
    named = len(_live_projects(inst, units)) > 1
    return [
        f"emergency room {len(using)}/{inst.emergency_extra} used by "
        f"{', '.join(unit.id for unit in using)}" + (f" ({unit_label(using[0])})" if named else "")
        for _key, using in sorted(
            lane_use.items(), key=lambda item: (item[0].repo, item[0].project)
        )
        if inst.emergency_extra
    ]


def _deadlock_lines(units: list[StoredUnit]) -> list[str]:
    """One line for each cycle of units waiting on each other, which can never start."""
    return [
        f"deadlocked: {' -> '.join(cycle)} ({len(cycle) - 1} units wait on each other "
        "and cannot start)"
        for cycle in deadlocks(units)
    ]


def _deadlocked_unit_lines(units: list[StoredUnit]) -> list[str]:
    """Each unit in a cycle, and each planned unit waiting on one directly or through
    others, with why it cannot start, under a heading; none when there is no deadlock."""
    stuck: dict[str, str] = {}
    for cycle in deadlocks(units):
        for unit_id in cycle[:-1]:
            stuck[unit_id] = " -> ".join(cycle)
    if not stuck:
        return []
    by_id = {unit.id: unit for unit in units}
    lines = [
        f"  deadlocked: {unit_id} ({unit_label(by_id[unit_id])}) is in the cycle {chain}"
        for unit_id, chain in stuck.items()
    ]
    behind: dict[str, str] = dict(stuck)
    grew = True
    while grew:
        grew = False
        for unit in units:
            if unit.id in behind or unit.state != PLANNED:
                continue
            parents = [p.id for p in shown_waits(unit, units) if p.id in behind]
            if parents:
                behind[unit.id] = behind[parents[0]]
                lines.append(
                    f"  {unit.id} ({unit_label(unit)}) waits on {', '.join(parents)}, "
                    f"deadlocked in {behind[parents[0]]}"
                )
                grew = True
    return ["cannot start:", *lines]


def _blocked_lines(
    units: list[StoredUnit],
    project: Hashable = EVERY_SLOT,
    slot_of: Callable[[Unit], Hashable] = project_key,
) -> list[str]:
    """One line for each blocked unit that has work and so is not counted, with what it waits on;
    only those of the slot `project` unless it is `EVERY_SLOT`."""
    lines = []
    for unit in uncounted(units):
        if project is not EVERY_SLOT and slot_of(unit) != project:
            continue
        waits = [parent.id for parent in shown_waits(unit, units)]
        lines.append(f"  blocked: {unit.id} ({unit_label(unit)}) waits on {', '.join(waits)}")
    return lines


# How near done a unit is, by state: the nearer, the less likely it is the one to retire.
_PROGRESS = {UNPLANNED: 0, PLANNED: 1, FAILED: 2, HELD: 2, RUNNING: 3, IN_REVIEW: 3}


def _collision_lines(units: list[StoredUnit]) -> list[str]:
    """One line for each group that two units that have started and not finished carry,
    suggesting the unit further from done to retire."""
    owners: dict[tuple[str, int], list[StoredUnit]] = {}
    for unit in units:
        if unit.owns_groups and not unit.unstarted:
            for member in unit.members():
                for group in member.groups:
                    owners.setdefault((member.change, group), []).append(unit)
    lines = []
    for (change, group), carrying in sorted(owners.items()):
        if len(carrying) < 2:
            continue
        # The later in plan order on a tie.
        far = max(carrying, key=lambda u: (-_PROGRESS.get(u.state, 0), units.index(u)))
        who = ", ".join(f"{u.id} ({u.state.value})" for u in carrying)
        lines.append(
            f"  group {group} of {change} is carried by {who} — suggestion: "
            f'abk retire {far.id} --reason "..."'
        )
    return lines


def _unplanned_work_lines(units: list[StoredUnit]) -> list[str]:
    """One line for each unplanned unit that holds work, with the command to end it, and a note
    when a merged unit carries all its groups."""
    lines = []
    for unit in units:
        if unit.state != UNPLANNED or not unit.has_work:
            continue
        fates = retirement.assess(unit.id, units).groups
        note = ""
        if fates and all(fate.merged for fate in fates):
            built = ", ".join(sorted({fate.carried_by for fate in fates}))
            note = f" — nothing is lost: its groups are in {built}"
        lines.append(
            f"  unplanned with work: {unit.id} ({unit_label(unit)}) — "
            f'abk retire {unit.id} --reason "..."{note}'
        )
    return lines


def _retire_lines(units: list[StoredUnit]) -> list[str]:
    """The units a person may want to retire, each with the command to run."""
    return [*_collision_lines(units), *_unplanned_work_lines(units)]


def _second_parent_lines(units: list[StoredUnit]) -> list[str]:
    """One line for each unit that has never started and waits for a second open parent."""
    return [
        f"  {unit.id} ({unit_label(unit)}) {wait}"
        for unit in units
        if (wait := second_parent_wait(unit, units))
    ]


def _replaced_lines(units: list[StoredUnit]) -> list[str]:
    """One line for each replaced unit that an unfinished unit's dependencies, `needs` or
    recorded wait still name, which is a pass that has not yet run."""
    named = {
        uid
        for unit in units
        if unit.state not in FINISHED
        for uid in (*unit.depends_on, *unit.needs, *unit.waited_on)
    }
    return [
        f"  replaced: {unit.id} by {', '.join(unit.superseded_by)}"
        for unit in units
        if unit.state in BUILDS_NOTHING and unit.superseded_by and unit.id in named
    ]


def _failed_waiting_lines(units: list[StoredUnit]) -> list[str]:
    """One line for each failed unit that waits on another unit, with what it waits on."""
    repos = config.active().repos
    lines = []
    for unit in failed_waiting_units(units):
        waits = shown_waits(unit, units)
        wait = dependency_wait(waits, merging=merge_parents(unit, waits, units, repos))
        lines.append(
            f"  failed, waiting on {', '.join(parent.id for parent in waits)}: "
            f"{unit.id} ({unit_label(unit)}) — {wait}"
        )
    return lines


def _wait_ended_lines(inst: Installation, units: list[StoredUnit]) -> list[str]:
    """The failed units left failed because a prerequisite closed, and, unless the requeue is
    off, how many were resumed today because their wait ended."""
    lines = [
        f"  {unit.id} ({unit_label(unit)}) wait ended: {unit.wait_ended} closed, requeue to retry"
        for unit in units
        if unit.state == FAILED and unit.wait_ended
    ]
    if inst.config.global_limits.wait_end_requeue is config.WaitEndRequeue.OFF:
        return lines
    today = spans.clock.now().astimezone().date()
    resumed = sum(
        1
        for unit in units
        for entry in unit.history
        if str(entry.get("note", "")).startswith(f"requeue: {WAIT_ENDED}")
        and (at := history_stamp(entry)) is not None
        and at.astimezone().date() == today
    )
    if resumed:
        lines.append(f"failed units resumed when their wait ended: {resumed} today")
    return lines


def _is_looping(inst: Installation, unit: StoredUnit) -> bool:
    """Whether a planned unit has been put back as many times in a row with one cause as
    `global_limits.bounce_limit` names. Visibility only: nothing schedules on it."""
    return unit.state == PLANNED and unit.bounces >= inst.config.global_limits.bounce_limit


def _ready_queue_lines(inst: Installation, units: list[StoredUnit]) -> list[str]:
    """The ready queue in the order the scheduler starts it, with why each unit is where it is."""
    attached = {held.unit_id for held in Leases(lease_dir(inst.state_dir)).attachments()}
    ready, view, excluded, _for_the_lane, _emergency = _evaluate_round(
        inst,
        units,
        started=attached,
        building=set(),
        only=frozenset(),
        enforce_limit=False,
        max_concurrent=len(units),
    )
    # With the real limits, the starts that only the emergency lane makes possible.
    *_, lane_only = _evaluate_round(inst, units, started=attached, building=set(), only=frozenset())
    if not ready:
        return []
    lines = ["ready queue (start order):"]
    handed_off = {unit.id for unit in handoff_units(ready, view, excluded)}
    stored = {unit.id: unit for unit in units}
    for place, unit in enumerate(ready, start=1):
        if note := priority_note(unit, view, excluded):
            why = note
        elif source := stack_age_source(unit, view, excluded):
            why = f"stack age, from {source.id}"
        else:
            why = "planned order"
        marker = " (handoff)" if unit.id in handed_off else ""
        marker += " (emergency room)" if unit.id in lane_only else ""
        marker += " (looping)" if _is_looping(inst, stored[unit.id]) else ""
        lines.append(f"  {place}. {unit.id} ({unit_label(unit)}) — {why}{marker}")
    return lines


def _log_ready(
    inst: Installation, store: UnitStore, ready: list[Unit], *, only: frozenset[str]
) -> None:
    """Log the units about to start, and why one goes ahead of an older ready unit.

    A unit that takes the age of an older unit waiting on it starts before ready
    units planned earlier than itself; the line names the unit it passed and the
    waiter whose age it took. The comparison ignores the limit on units in
    progress: a unit that fits under it is passed by one that took the place.
    """
    log(f"ready: {', '.join(unit.id for unit in ready)}")
    units = store.all()
    queue, view, excluded, _for_the_lane, _emergency = _evaluate_round(
        inst,
        units,
        started=set(),
        building=set(),
        only=only,
        enforce_limit=False,
        max_concurrent=len(units),
    )
    place = {unit.id: index for index, unit in enumerate(view)}
    order = [unit.id for unit in queue]
    for unit in ready:
        source = stack_age_source(unit, view, excluded)
        if source is None or unit.id not in order:
            continue
        passed = next(
            (
                other
                for other in queue[order.index(unit.id) + 1 :]
                if place[other.id] < place[unit.id]
                and effective_priority(other, view, excluded)
                == effective_priority(unit, view, excluded)
            ),
            None,
        )
        if passed is not None:
            log(f"{unit.id} starts ahead of {passed.id}: {source.id} waits on it")


def _blocked_by(unit: StoredUnit, units: list[StoredUnit]) -> str:
    """What a failed unit holds up, with the way to free it; empty when nothing waits."""
    waiting = len(waiting_on_me(unit, units))
    if not waiting:
        return ""
    noun = "unit" if waiting == 1 else "units"
    return (
        f"{unit.id} ({unit_label(unit)}) has {waiting} {noun} waiting on it — "
        "requeue it with `abk requeue`"
    )


def _nothing_started_reason(
    inst: Installation, units: list[StoredUnit], *, only: frozenset[str], paused: bool = False
) -> str:
    """Why a pass starts nothing: the limit, when lifting it would start a
    unit, and otherwise that nothing is ready, with a line for each candidate unit
    unless a pause is in force, which the pause line already tells. A deadlock comes first."""
    cycles = deadlocks(units)
    if cycles:
        return "nothing can start: " + "; ".join(
            f"deadlocked: {' -> '.join(cycle)}" for cycle in cycles
        )
    slot_of = _slot_of(inst)
    full_projects = _queue_full_by_project(inst, units)
    if full_projects:
        ready = _evaluate(
            inst,
            units,
            started=set(),
            building=set(),
            only=only,
            enforce_limit=False,
            idle=_idle_units(inst, units, ()),
        )
        held_back = {slot_of(unit) for unit in ready}
        lines = []
        for key, line in full_projects.items():
            if key in held_back:
                lines.append(
                    f"{line}; {_WAIT_FOR_ROOM if inst.emergency_extra else _WAIT_FOR_ROOM_OFF}"
                )
                lines.extend(_blocked_lines(units, key, slot_of))
        if lines:
            return "\n".join(lines)
    failed = [line for unit in units if unit.state == FAILED and (line := _blocked_by(unit, units))]
    if failed:
        return "nothing can start: " + "; ".join(failed)
    if paused:
        return "nothing ready to build"
    return "\n".join(["nothing ready to build", *_candidate_lines(inst, units, only=only)])


_WAIT_FOR_ROOM_OFF = "no new unit starts until one finishes or is closed"
_WAIT_FOR_ROOM = (
    "no ordinary unit starts until the occupancy is below the limits, "
    "except a ready priority-0 unit while the lane has room"
)

# How many candidate units a tick that builds nothing names.
NOTHING_READY_UNITS = 10

# The reasons a person can act on soonest: they come first among the lines.
_ACTIONABLE_REASONS = frozenset(
    {WaitReason.READY, WaitReason.SLOT, WaitReason.LEASE, WaitReason.BACKOFF}
)


def _candidate_lines(
    inst: Installation, units: list[StoredUnit], *, only: frozenset[str]
) -> list[str]:
    """One line for each planned, held or failed unit with its wait reason and what it waits
    on, at most `NOTHING_READY_UNITS`, then how many were left out. A report line never fails
    a tick: when the reasons cannot be computed, one line names the error."""
    try:
        waits = wait_reasons(
            inst,
            units,
            started=set(),
            building=set(),
            only=only,
            idle=_idle_units(inst, units, ()),
        )
        candidates = [
            (unit, waits[unit.id])
            for unit in units
            if unit.state in (PLANNED, HELD, FAILED) and unit.id in waits
        ]
    except Exception as error:  # noqa: BLE001 — a report line never fails a tick
        return [f"  (the reasons could not be worked out: {type(error).__name__}: {error})"]
    candidates.sort(key=lambda found: found[1].reason not in _ACTIONABLE_REASONS)
    lines = []
    for unit, why in candidates[:NOTHING_READY_UNITS]:
        waiting = f", waits on {', '.join(why.waits_on)}" if why.waits_on else ""
        lines.append(f"  {unit.id} ({unit_label(unit)}): {why.reason.value}{waiting}")
    if len(candidates) > NOTHING_READY_UNITS:
        lines.append(f"  (+{len(candidates) - NOTHING_READY_UNITS} more)")
    return lines


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
# build — an e2e-test run, a slow review — blind for its whole length, and the
# timer cannot start a second tick while this one is running.
REFRESH_SECONDS = 300.0

# How many times a pass may start a unit that it already built and that a poll
# then sent back (a conflict, a failing check, a review comment). Bounded so a
# pass still ends.
REBUILDS_PER_PASS = 2


# The causes a unit put back to planned is let back into the running pass for: sent
# back for rework by a poll, or held by its own build because the branch it builds
# on changed. Resuming restacks the unit onto its new base before anything else, so
# that cause is gone by the time it runs again — unlike an unfinished upstream or a
# full usage window, which a rerun would only meet again. `RESTACK_HANDED_BACK` is a
# moved-base run the restack lane gave back to a build worker.
READMITTED_CAUSES = frozenset({Cause.REWORK, Cause.BASE_CHANGED, Cause.RESTACK_HANDED_BACK})


def _sent_back(
    units: list[StoredUnit],
    started: dict[str, int],
    building: set[str],
    skipped: set[tuple[str, str]] | None = None,
) -> set[str]:
    """Units this pass already built that have since been put back to planned for
    a cause in `READMITTED_CAUSES`, or parked for `host_unavailable` once its backoff
    has elapsed. A unit put back for any other cause, or for none
    (a record from before causes were kept), waits for the next pass, and a unit that
    ended held is never let back in; each such skip is logged once, with its cause,
    in `skipped`. "Since" is the unit's history having grown past its length when the
    pass started it, never a comparison of timestamps: a clock that steps back or
    stands still must not decide it."""
    out: set[str] = set()
    for unit in units:
        at = started.get(unit.id)
        if (
            at is None
            or unit.id in building
            or unit.state not in (PLANNED, HELD)
            or not unit.history
        ):
            continue
        if len(unit.history) <= at:
            continue
        # Keyed on when the cause was set, so a carried entry does not log the skip again.
        since = str(unit.cause_since)
        if unit.state == PLANNED and unit.cause in READMITTED_CAUSES:
            out.add(unit.id)
        elif (
            unit.state == PLANNED
            and unit.cause in PARKED_CAUSES
            and backoff_remaining(unit, spans.clock.now()) is None
        ):
            out.add(unit.id)
        elif (
            skipped is not None
            and unit.cause is not None
            # Readmitted by a later round once its backoff is over.
            and unit.cause not in PARKED_CAUSES
            and (unit.id, since) not in skipped
        ):
            skipped.add((unit.id, since))
            log(f"{unit.id}: not started again in this pass, stopped for {unit.cause.value}")
    return out


def _schedule(
    inst: Installation,
    ready: list[Unit],
    *,
    store: UnitStore,
    only: frozenset[str],
    readmission: _Readmission,
    lane: Lane,
) -> int:
    """Keep the build slots full until nothing more is ready.

    Every completion may release something — a parent's PR opening lets its
    child stack on it, a dependency merging releases its dependent — so each
    one is followed by a refresh from GitHub and a fresh evaluation, rather
    than waiting for the whole batch and the next tick. The refresh asks
    GitHub rather than hearing from it, since a tick has no endpoint for a
    webhook to reach; a completion is when it asks. Only the model's own
    refusal (a `rate_limit` pause, or a build returning False) ends
    submission. A usage refusal pauses only that unit: later rounds ask the
    guard again and resume it. The builds already running are still awaited,
    since each checks the usage guard itself and killing one would leave its
    work uncommitted.

    The refresh runs while other builds are still going, so what it hears may
    concern one of them. The event handlers leave a unit whose build holds its
    lock untouched and the poller reports the event again later — see
    `events` — which the refresh after that build's own completion does.

    A repo found mid-pass with no commit identity stops submission for every
    repo, not only that one, for the rest of the pass; the builds in flight
    are still awaited and the pass exits 1, as it does when the check fails
    at the start.
    """
    started = readmission.started
    building: dict[Future[bool], Unit] = {}
    # Units that could build but for the slots, from when they were first seen so.
    queued: dict[str, spans.Mark] = {}
    failed = False
    refused = False
    with ThreadPoolExecutor(
        max_workers=_pool_size(inst, store.all()), thread_name_prefix="unit"
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
            unstamped = {unit.id for unit in units if unit.ready_at is None}
            for unit in evaluated:
                if unit.id in unstamped:
                    store.mark_ready(unit.id)
                if unit.id not in taken:
                    queued.setdefault(unit.id, spans.Mark())

        def sample() -> None:
            """One ledger row and the slot gauges, for a wake once its slots are refilled:
            what is in flight counts as running though its worker has not yet marked it so."""
            units = store.all()
            states = [unit.state for unit in units]
            in_flight = {unit.id for unit in building.values()}
            occupied = slot_occupancy(
                units,
                in_flight,
                lane.running,
                lane_waiting=lane.waiting,
                idle=_idle_units(inst, units, in_flight),
            )
            running = set().union(*occupied.values())
            # Totals over the projects with a unit not yet finished, for reporting only.
            live = _unfinished_projects(units)
            free = sum(
                max(0, inst.max_concurrent_stacks - len(occupied.get(key, ()))) for key in live
            )
            spans.record_sample(
                spans.Sample(
                    at=spans.clock.now().isoformat(),
                    running=len(running),
                    in_review=states.count(IN_REVIEW),
                    blocked=sum(
                        1 for unit in units if unit.state == PLANNED and waiting_on(unit, units)
                    ),
                    queued=len(queued),
                    free_workers=free,
                    limit=_slots_capacity(inst, units, live),
                    cap=inst.max_concurrent_stacks * len(live),
                ),
                log,
            )
            telemetry.level("abk.slots.free", free)
            telemetry.level("abk.slots.idle_with_ready", min(free, len(queued)))
            telemetry.level(
                "abk.slots.emergency_used",
                len(emergency_lane.users(inst.state_dir, _with_builds_running(units, in_flight))),
            )
            telemetry.level("abk.restacks.running", len(lane.running))
            telemetry.level("abk.restacks.waiting", len(lane.waiting))

        def submit(units: list[Unit]) -> None:
            for unit in units:
                started[unit.id] = len(store.get(unit.id).history)
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
        # A restack in the lane is waited for as a build is, and ends a pass only when it has.
        # Whether the lane had work when the round last looked, and still has: a restack that
        # ends after a round left its unit out is followed by one more round, which starts it.
        lane_busy = bool(lane.running or lane.waiting)
        while building or lane_busy or lane.running or lane.waiting:
            # A lane with nothing to do has nothing to wake the pass for.
            lane_ends = lane.finished()
            waited_on: list[Future[Any]] = [*building]
            if not lane_ends.done():
                waited_on.append(lane_ends)
            done, _ = wait(waited_on, timeout=REFRESH_SECONDS, return_when=FIRST_COMPLETED)
            for future in done:
                if future not in building:
                    continue
                ended = building.pop(future)
                # A build the model refused returns False too, and pauses its own account: that
                # stops the pass only when it leaves no account to start on (below).
                if not future.result() and not _refused_by_model(inst, ended):
                    failed = True
            lane.scan(store.all())
            lane_busy = bool(lane.running or lane.waiting)
            # A build still in flight — or another tick — may already have
            # recorded the model's refusal; its report is not needed to stop
            # here. A usage pause is not one: the round asks the guard again. One account's
            # refusal does not stop the others, so it takes every account in use.
            refused_labels = {
                each.account
                for each in pauses_in_force(inst.state_dir)
                if each.kind == "rate_limit"
            }
            stopping = (
                failed
                or {each.label for each in claude_account.in_use(inst.config)} <= refused_labels
            )
            if stopping or refused:
                sample()
                continue

            in_flight = {unit.id for unit in building.values()}
            ready = run_round(
                inst,
                store,
                building=in_flight,
                only=only,
                submit=True,
                readmit=readmission,
                quiet=True,
                refused_needs=readmission.refused,
                lane=lane,
            )
            units = store.all()
            note_queued(units, ready, in_flight)
            if ready:
                _log_ready(inst, store, ready, only=only)
                if _refuse_unconfigured(inst, ready):
                    refused = True
                    sample()
                    continue
                submit(ready)
            sample()
    return 1 if refused else 0


def _live_projects(inst: Installation, units: list[StoredUnit]) -> set[ProjectKey]:
    """The projects a repo declares, and those with a unit not yet finished."""
    live = {ProjectKey(repo=repo) for repo in inst.repos}
    for repo, paths in declared_projects(inst.repos).items():
        live |= {ProjectKey(repo=repo, project=path) for path in paths}
    return live | _unfinished_projects(units)


def _pool_size(inst: Installation, units: list[StoredUnit]) -> int:
    """Threads for every project's build workers together; each project's own count is the only
    limit on what starts."""
    return (inst.max_concurrent_stacks + inst.emergency_extra) * len(_live_projects(inst, units))


def _refresh(inst: Installation, *, store: UnitStore, lane: Lane | None = None) -> None:
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
        poll_all(inst, store=store, lane=lane)
    except Exception as error:  # noqa: BLE001
        # GitHub being unreachable is a reason to skip the update, not to stop
        # building units whose work doesn't depend on it.
        log(f"poll skipped — {type(error).__name__}: {error}")
    # What the poll found, and what it left owed, whether or not the host answered.
    if lane is not None:
        lane.scan(store.all())


def park_dependents(inst: Installation, store: UnitStore) -> None:
    """Park the units in review whose predecessor's branch is changing, each by an
    event to its thread."""

    def deliver(unit: StoredUnit, note: str) -> bool:
        resumed = resume_thread(
            inst, unit, EventKind.UPSTREAM_CHANGED.value, store=store, reason=note
        )
        return resumed is not None and not resumed.raised

    follow_predecessors(
        store,
        head=partial(branch_head, inst),
        claim=build_claim(inst.state_dir / "locks"),
        deliver=deliver,
        log=log,
    )


def branch_head(inst: Installation, unit: StoredUnit) -> str:
    """The commit a unit's branch is at in its repo's checkout, or an empty
    string when it has none."""
    path = inst.checkouts.get(unit.repo)
    if path is None:
        return ""
    ref = f"refs/heads/{unit.branch or branch_name(unit)}"
    return git(path, "rev-parse", "--verify", "-q", ref, check=False).stdout.strip()


def parked_units(inst: Installation, units: Sequence[StoredUnit]) -> frozenset[str]:
    """The running units a pause in force has parked: no run holds their branch, so the
    pause is what they wait on. A build in flight goes on through a pause until its next
    agent step, and is not one. Computed once for a view that shows many units."""
    if not pause_in_force(inst.state_dir):
        return frozenset()
    return frozenset(
        unit.id
        for unit in units
        if unit.state == RUNNING
        and _paused_for(inst, unit) is not None
        and not branch_is_held(inst, unit.branch or branch_name(unit))
    )


def branch_is_held(inst: Installation, branch: str) -> bool:
    """Whether a live process holds this branch's lock.

    Read from the lock's pid and never taken, so asking never turns away a run starting on
    the branch; `workspaces.branch_held` does the reading.
    """
    return branch_held(branch, root=inst.state_dir / "locks")


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


def _create_thread_store(inst: Installation) -> None:
    """Create the thread database before units start in parallel: its first open
    switches it to WAL, which two connections racing to do fail on with a lock."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path

    async def create() -> None:
        async with open_checkpointer(unit_graphs_path(inst.state_dir)):
            pass

    asyncio.run(create())


def link_needs(
    inst: Installation,
    *,
    store: UnitStore,
    reported: set[tuple[str, str]] | None = None,
) -> list[CycleEdge]:
    """Apply every change's `Needs:` lines as unit dependencies.

    Every tick, after planning: a re-plan takes each unit's dependencies from
    the plan, which knows nothing of these, so linking once would not last.
    Idempotent — a target the unit already reaches is left alone. The dependencies
    refused because they would close a cycle are returned and logged, but not again
    for a pair already in `reported`, which a pass keeps across its rounds.
    """
    units = store.all()
    live = [unit for unit in units if unit.state not in BUILDS_NOTHING]
    declared = declared_needs(
        inst,
        live,
        missing=lambda change, group, need: log(
            f"{change} group {group} needs {need.change} group {need.group}, not planned yet"
        ),
    )
    wanted = {unit_id: [d.target for d in found] for unit_id, found in declared.items()}
    refused = _repoint_replaced(units, wanted, store, reported)
    units = _drop_stale_edges(store, store.all(), wanted)
    graph = {u.id: list(current_dependencies(u, units)) for u in units if u.state not in FINISHED}
    written = {tasks.parent.name for tasks in inst.tasks_files()}
    # Every stored edge, of units in any state: a merged unit between two still links them.
    stored = {u.id: list(current_dependencies(u, units)) for u in units}
    for unit in units:
        if unit.id not in wanted and not unit.needs:
            continue
        added: list[str] = []
        needs: list[str] = []
        merge_targets = {d.target for d in declared.get(unit.id, []) if d.merge}
        for target in dict.fromkeys(wanted.get(unit.id, [])):
            if path_between(stored, unit.id, target):
                needs.append(target)
                continue
            if back := path_between(graph, target, unit.id):
                _refuse_cycle(unit.id, target, back, reported, refused)
                continue
            added.append(target)
            needs.append(target)
            graph.setdefault(unit.id, []).append(target)
            stored[unit.id].append(target)
        if added:
            # The store keeps the direct ones: a listed dependency an added target reaches goes.
            store.set_dependencies(unit.id, (*unit.depends_on, *added))
            stored[unit.id] = list(store.get(unit.id).depends_on)
            log(f"{unit.id}: now depends on {', '.join(added)} (Needs: in tasks.md)")
        # Which targets a `Needs:` line named, linked or implied, for the graph alone; a
        # removed line removes the mark.
        if tuple(needs) != unit.needs:
            store.set_needs(unit.id, needs)
        # A change with no tasks to read has nothing to recompute the kind from, so it keeps it.
        merge = tuple(t for t in needs if t in merge_targets)
        if unit.change in written and merge != unit.merge_needs:
            store.set_merge_needs(unit.id, merge)
            _note_merge_waits(unit, [t for t in merge if t not in unit.merge_needs], units)
    return refused


def _note_merge_waits(unit: StoredUnit, gained: list[str], units: list[StoredUnit]) -> None:
    """Say that an unfinished `unit` (planned, failed or held) now waits for each `gained` merge
    target in its own repository, which only a written `merged` makes a merge wait, when that
    parent has not landed; nothing is edited or requeued and a started unit is not named."""
    if unit.state not in (PLANNED, FAILED, HELD):
        return
    by_id = {u.id: u for u in units}
    for parent_id in gained:
        parent = by_id.get(parent_id)
        if parent is None or parent.repo != unit.repo:
            continue
        if parent.state in (CLOSED, *BUILDS_NOTHING) or parent_landed(parent, units):
            continue
        log(f"{unit.id}: now waits for {parent_id} to merge (Needs: ... merged in tasks.md)")


def _drop_stale_edges(
    store: UnitStore, units: list[StoredUnit], wanted: dict[str, list[str]]
) -> list[StoredUnit]:
    """Remove each stored dependency, of a unit still to be built, on a unit that builds
    nothing, has no successor and that no `Needs:` line declares;
    the units as the store has them after."""
    index = {unit.id: unit for unit in units}
    changed = False
    for unit in units:
        if unit.state in FINISHED or unit.state in BUILDS_NOTHING:
            continue
        stale = [
            dep
            for dep in unit.depends_on
            if (parent := index.get(dep)) is not None
            and parent.state in BUILDS_NOTHING
            and not parent.superseded_by
            and dep not in wanted.get(unit.id, ())
        ]
        if not stale:
            continue
        store.set_dependencies(unit.id, [d for d in unit.depends_on if d not in stale])
        for dep in stale:
            log(f"{unit.id}: dropped dependency {dep}: it builds nothing")
        changed = True
    return store.all() if changed else units


def _refuse_cycle(
    unit_id: str,
    target: str,
    back: Sequence[str],
    reported: set[tuple[str, str]] | None,
    refused: list[CycleEdge],
) -> None:
    """Refuse `target` as a dependency of `unit_id` because `back` runs from it to the unit:
    log it unless the pair was already `reported`, and add it to `refused`."""
    edge = CycleEdge(unit=unit_id, dependency=target, cycle=(unit_id, *back))
    if reported is None or (unit_id, target) not in reported:
        cycle = " -> ".join(edge.cycle)
        log(f"{unit_id}: Needs: {target} refused, it would close the cycle {cycle}")
    if reported is not None:
        reported.add((unit_id, target))
    refused.append(edge)


def record_successors(store: UnitStore) -> None:
    """Give units replaced before successors were recorded theirs, once, before linking."""
    if written := store.backfill_successors():
        log(f"successors recorded: {len(written)} unit(s)")


def _repoint_replaced(
    units: Sequence[StoredUnit],
    wanted: Mapping[str, Sequence[str]],
    store: UnitStore,
    reported: set[tuple[str, str]] | None,
) -> list[CycleEdge]:
    """Replace each stored dependency of an unfinished unit on a replaced unit by the live
    units that carry its work now. When the unit's `Needs:` lines resolve to some of them only
    those are taken. A target that would close a cycle is refused as a `Needs:` is, and with
    none left the stored dependency stays. The unit itself is never a target: when it is the
    only successor the dependency is dropped, as the unit carries that work. Returns the
    refusals."""
    graph = {u.id: list(current_dependencies(u, units)) for u in units if u.state not in FINISHED}
    refused: list[CycleEdge] = []
    by_id = {u.id: u for u in units}
    for unit in units:
        if unit.state in FINISHED or unit.state in BUILDS_NOTHING:
            continue
        depends = list(unit.depends_on)
        for old in unit.depends_on:
            found = by_id.get(old)
            if found is None or found.state not in BUILDS_NOTHING or not found.superseded_by:
                continue
            # A successor the store does not hold stands for itself and builds nothing here.
            resolved = resolve_replaced(old, units)
            live = [
                t
                for t in resolved
                if t not in (old, unit.id)
                and (carrier := by_id.get(t))
                and carrier.state not in BUILDS_NOTHING
            ]
            narrowed = [t for t in live if t in wanted.get(unit.id, ())]
            kept: list[str] = []
            for target in narrowed or live:
                if back := path_between(graph, target, unit.id):
                    _refuse_cycle(unit.id, target, back, reported, refused)
                    continue
                kept.append(target)
            if not kept:
                if unit.id in resolved and not live:
                    # The unit carries that work itself, so it has nothing to wait for.
                    depends.remove(old)
                continue
            at = depends.index(old)
            depends[at : at + 1] = kept
            log(f"{unit.id}: dependency {old} is now {', '.join(kept)} (replaced by a replan)")
        linked = tuple(dict.fromkeys(depends))
        if linked != unit.depends_on:
            store.set_dependencies(unit.id, linked)
    return refused


class DeclaredNeed(Frozen):
    """A unit a `Needs:` line names, and whether the line waits for its merge."""

    target: str
    merge: bool = False


def declared_needs(
    inst: Installation,
    units: Sequence[Unit],
    *,
    missing: Callable[[str, int, Need], object] | None = None,
) -> dict[str, list[DeclaredNeed]]:
    """The units each unit's `Needs:` lines name, for the `units` that cover the groups.
    A line waits for the merge when it says `merged` or the target is in another repository.

    A line naming a group none of them covers adds nothing; `missing` hears of it."""
    covering = {
        (member.change, group): unit.id
        for unit in units
        for member in unit.members()
        for group in member.groups
    }
    repo_of = {unit.id: unit.repo for unit in units}
    wanted: dict[str, list[DeclaredNeed]] = {}
    for tasks in inst.tasks_files():
        change = tasks.parent.name
        for group, found in group_needs(tasks).items():
            for need in found:
                if (need.change, need.group) not in covering and missing:
                    missing(change, group, need)
            for unit in units:
                if any(m.change == change and group in m.groups for m in unit.members()):
                    wanted.setdefault(unit.id, []).extend(
                        DeclaredNeed(
                            target=covering[(n.change, n.group)],
                            merge=n.merged or repo_of[covering[(n.change, n.group)]] != unit.repo,
                        )
                        for n in found
                        if (n.change, n.group) in covering
                    )
    return wanted


# Units a plan is made around and never changes: their groups are built or being
# built, a failed or held unit's too, which wait for a person and keep their branch.
_STARTED = (*IN_FLIGHT, FAILED, HELD, MERGED, SATISFIED)

# Why a change needs no plan, as `plan_all` logs it and `abk replan` prints it.
ALL_TAKEN = (
    "every group is taken by a started unit or another change's planned unit, which reads the edit"
)


class PlanResult(Frozen):
    """What `plan_all` did for one change: `planned`, `failed`, `waiting` (an outage, no
    attempt used), `refused` (the tags are wrong) or `skipped` (nothing asked for a plan)."""

    status: Literal["planned", "failed", "waiting", "refused", "skipped"]
    dropped_joins: int = 0
    # Recorded as planned without asking: every group is taken, by a started unit or by
    # another change's planned unit.
    recorded_only: bool = False
    # A cycle of `Needs:` and stored dependencies alone, which no planner edge could be
    # dropped from: the plan stands and this names it.
    cycle: tuple[str, ...] = ()
    # Planned units of the change with work that the plan left out, and so kept as they were.
    kept: tuple[str, ...] = ()


def _carried(store: UnitStore, change: str, keep: Callable[[StoredUnit], bool]) -> set[int]:
    """The numbers of `change`'s groups carried, its own or joined, by units `keep` accepts."""
    return {
        number
        for u in store.all()
        if keep(u)
        for member in u.members()
        if member.change == change
        for number in member.groups
    }


def _taken_groups(store: UnitStore, change: str) -> set[int]:
    """The numbers of `change`'s groups no plan may claim: those a unit that has started
    carries, and those another change's planned unit carries."""
    return _carried(
        store, change, lambda u: u.state in _STARTED or (u.state == PLANNED and u.change != change)
    )


def _task_group_problems(count: int) -> str:
    """How refusing a change with broken task groups reads in a tick, a replan and its report."""
    return f"{count} task-group problem(s) — run `abk tags`"


def _gone_groups_reason(store: UnitStore, change: str, groups: Sequence[TaskGroup]) -> str | None:
    """Why no plan is made while a started unit carries a group `tasks.md` no longer has,
    or None when every such group is still there."""
    if not (gone := _gone_groups(store, change, groups)):
        return None
    numbers = ", ".join(str(n) for n in gone)
    return (
        f"group(s) {numbers} are built by a started unit "
        "but are no longer in tasks.md — restore or renumber them back"
    )


def _without_planner(
    inst: Installation,
    store: UnitStore,
    change: str,
    task_groups: Sequence[TaskGroup],
    errors: Sequence[object],
) -> tuple[Literal["refused", "tag_problems", "all_taken"], str | list[str]] | None:
    """Why a plan for `change` is made without the planner, or None when it would be called:
    `refused` with the reason (broken task groups, or groups gone from `tasks.md`),
    `tag_problems` with a line each when every group is taken and a tag disagrees, or
    `all_taken` with `ALL_TAKEN`. The one place `plan_all` and `abk replan --report` decide."""
    if errors:
        return "refused", _task_group_problems(len(errors))
    if gone := _gone_groups_reason(store, change, task_groups):
        return "refused", gone
    # Nothing is left for the planner when every group is taken: each started unit
    # reads tasks.md at its next step, so an edit of the text needs no plan. Only the
    # tags it copied at plan time can disagree with the file.
    if task_groups and _taken_groups(store, change) >= {g.number for g in task_groups}:
        if problems := _tag_problems(store, change, task_groups, _task_catalog(inst)):
            return "tag_problems", problems
        return "all_taken", ALL_TAKEN
    return None


def _gone_groups(store: UnitStore, change: str, groups: Sequence[TaskGroup]) -> list[int]:
    """The groups a started unit carries that `tasks.md` no longer has: renumbered or deleted."""
    carried = _carried(store, change, lambda u: u.state in _STARTED)
    return sorted(carried - {g.number for g in groups})


def _task_catalog(inst: Installation) -> dict[str, tuple[TaskGroup, ...]]:
    """Every change's task groups, as `unit_priority` and the plan check read them."""
    return {path.parent.name: tuple(_validated(inst, path)[0]) for path in inst.tasks_files()}


def _set_priorities(
    store: UnitStore, ids: Iterable[str], catalog: Mapping[str, Sequence[TaskGroup]]
) -> None:
    """Each unit's priority from the groups it builds now; a unit that has started keeps
    what it has (the store ignores it)."""
    for unit_id in dict.fromkeys(ids):
        store.set_priority(unit_id, unit_priority(store.get(unit_id), catalog))


def _carrying_unstarted(store: UnitStore, change: str) -> list[str]:
    """The unstarted units that carry some of `change`'s groups: an edited line reaches
    them without a join naming them."""
    return [
        u.id for u in store.all() if u.unstarted and any(m.change == change for m in u.members())
    ]


def _tag_problems(
    store: UnitStore,
    change: str,
    groups: Sequence[TaskGroup],
    catalog: Mapping[str, Sequence[TaskGroup]],
) -> list[str]:
    """Where a started unit's stored repo, project, tier or flag differs from the tags of a group
    of `change` it carries, its own or joined. The stored tier is compared with the widest kind
    among all the groups the unit carries, of every change in `catalog`. Each line names the
    unit, the group and the way out; none when they agree."""
    by_number = {g.number: g for g in groups}
    lines: list[str] = []
    for u in store.all():
        if u.state not in _STARTED:
            continue
        way_out = "restore the tag"
        if u.state in (FAILED, HELD):
            way_out += f", or `abk requeue --restart {u.id}` rebuilds it from the new tags"
        checks: list[tuple[str, str, str, str]] = []
        carried_kinds: list[tuple[str, int, TestTier]] = []
        here = False
        all_found = True
        for member in u.members():
            known = (
                by_number
                if member.change == change
                else {g.number: g for g in catalog.get(member.change, ())}
            )
            for number in member.groups:
                if group := known.get(number):
                    carried_kinds.append((member.change, number, group.tier))
                else:
                    all_found = False
                if member.change != change:
                    continue
                if group := by_number.get(number):
                    here = True
                    checks += [
                        (f"its group {number}", "repo", u.repo, group.repo),
                        (f"its group {number}", "project", u.project, group.project),
                    ]
        # With a group missing (its change archived, or the group removed) the widest kind
        # cannot be known, so the stored tier is not compared.
        if here and all_found:
            widest = widest_kind(kind for _, _, kind in carried_kinds)
            # Named by the first group of that kind, the one that sets the unit's; a group
            # of another change is named with its change, since its number means nothing here.
            owner, first, _ = next(c for c in carried_kinds if c[2] == widest)
            named = f"its group {first}" + ("" if owner == change else f" of {owner}")
            checks.append((named, "tier", str(u.tier), str(widest)))
        # The flag is the unit's own first flagged group (see `plan_kind`). A record
        # from before flags were kept stores none, which says nothing about the group.
        if u.change == change and u.flag:
            checks.append(("its groups", "flag", u.flag, plan_kind(u, groups).flag))
        for which, field, stored, now in checks:
            if stored != now:
                lines.append(
                    f"{u.id} is {u.state.value} with {field} {stored or 'none'!r} but "
                    f"{which} is now {now or 'none'!r} — {way_out}"
                )
    return lines


REASON_LIMIT = 300


def _failure_reason(error: Exception) -> str:
    """What a plan record keeps of why an attempt failed: the first line of the error,
    its type named unless the planner refused the plan, with secrets removed and at most
    `REASON_LIMIT` characters."""
    text = str(error) if isinstance(error, PlannerError) else f"{type(error).__name__}: {error}"
    first = text.strip().splitlines()[0] if text.strip() else type(error).__name__
    return cut_head(redact_text(first, where="plan record"), REASON_LIMIT, "char")


def _previous_refusal(record: Mapping | None, digest: str) -> str:
    """Why the last attempt at this `tasks.md` was refused, or nothing when it failed for
    another reason or the file has changed since."""
    if record and record.get("hash") == digest and record.get("units"):
        return str(record.get("reason") or "")
    return ""


def _refusal(error: PlannerError) -> dict:
    """What a plan record keeps of a refused plan: the unit ids the planner returned
    and why it was refused, never its full reply."""
    return {"units": list(error.units), "reason": _failure_reason(error)}


PLAN_WAITS = {"network": "the network", "service": "the model service"}


def _plan_wait(inst: Installation, error: Exception, previous: Mapping) -> tuple[str, dict] | None:
    """The kind of wait an outage error makes of a plan, and the fields of the record
    that says so, or None when the failure counts as an attempt: a weak sign the probe
    does not confirm, or a run of statuses longer than
    `global_limits.service_unavailable_attempts`."""
    waiting = bool(previous.get("waiting"))
    waited = previous.get("waits", 0) if waiting else 0
    # Only statuses are capped: waits the probe found are not, and do not count.
    statuses = previous.get("service_waits", 0) if waiting else 0
    if isinstance(error, ServiceUnavailable):
        if statuses >= inst.config.global_limits.service_unavailable_attempts:
            return None
        statuses += 1
        kind = "service"
    elif isinstance(error, NetworkUnavailable):
        cause = _outage_cause(inst, error)
        if cause is None:
            return None
        kind = "network" if cause is Cause.NETWORK_UNAVAILABLE else "service"
    else:
        return None
    now = spans.clock.now()
    waits = waited + 1
    return kind, {
        "attempts": previous.get("attempts", 0),
        "waiting": kind,
        "waits": waits,
        "service_waits": statuses,
        "since": (previous.get("since") if waited else None) or now.isoformat(),
        "until": (now + PARK_BACKOFF[min(waits, len(PARK_BACKOFF)) - 1]).isoformat(),
        "reason": _failure_reason(error),
    }


def _standing_sizing(standing: dict | None, current: str) -> str:
    """The policy digest to record for a plan that failed or waits: the one of the plan that
    stands, so the change still reads as stale; the current one when nothing stands."""
    return standing.get("sizing", "") if standing else current


def plan_all(
    inst: Installation,
    *,
    store: UnitStore,
    only: Collection[str] | None = None,
    force: bool = False,
) -> dict[str, PlanResult]:
    """Turn each OpenSpec change into units, when it needs it.

    Planning is a model call, and a tick runs every few minutes — so a change
    is planned once, and again only when its `tasks.md` changes. The recorded
    hash is machine-local and losing it is harmless: `upsert` merges by unit
    id and keeps state, branch and PR, so re-planning costs a model call and
    nothing else.

    `only` limits it to those changes, and `force` plans them whatever the
    recorded plan says, with their failed attempts counted from none: what
    `abk replan` asks for. The result has an entry for each change visited.
    """
    planned = planned_hashes(inst)
    max_attempts = inst.max_plan_attempts
    sizing = sizing_digest()
    results: dict[str, PlanResult] = {}
    network_down = False

    # A change removed from the planning repo is never planned again, so its units that never
    # started would outlive it and hold the units that wait on them. A planning repo with no
    # changes directory at all is misconfigured, not empty, and drops nothing.
    if inst.changes_dir.is_dir():
        existing = {path.name for path in inst.changes_dir.iterdir() if path.is_dir()}
        if gone := store.unplan_vanished(existing):
            log(f"unplanned, their change no longer exists: {', '.join(gone)}")

    for tasks in inst.tasks_files():
        change = tasks.parent.name
        if only is not None and change not in only:
            continue
        if network_down:
            results[change] = PlanResult(status="skipped")
            continue
        record = {} if force else planned.get(change) or {}
        digest = plan_digest(tasks, record.get("hash"))

        # Attempts are counted against the content, not the change, so editing
        # tasks.md — which is the actual fix — starts them over.
        if _plan_rests(record, digest, max_attempts, spans.clock.now()):
            results[change] = PlanResult(status="skipped")
            continue

        # The tags are how a unit finds its repo and its tier. Planning
        # against a broken one spends a model call to produce a graph that
        # cannot be built, so this refuses before paying for it.
        task_groups, errors = _validated(inst, tasks)
        # A group a started unit carries must still be in tasks.md: renumbered or
        # deleted, the unit's branch and the groups no longer agree, so no plan is made.
        decided = _without_planner(inst, store, change, task_groups, errors)
        if decided is not None:
            kind, why = decided
            if kind == "refused":
                log(f"not planning {change}: {why}")
                results[change] = PlanResult(status="refused")
            elif kind == "tag_problems":
                for line in why:
                    log(f"{change}: {line}")
                results[change] = PlanResult(status="refused")
            else:
                # A planned unit of another change that carries a group has its priority
                # from the edited line, as the planning path gives it.
                _set_priorities(store, _carrying_unstarted(store, change), _task_catalog(inst))
                record_plans(
                    inst,
                    {change: {"hash": digest, "sizing": sizing, "attempts": 0, "ok": True}},
                )
                log(f"{change}: {why}")
                results[change] = PlanResult(status="planned", recorded_only=True)
            continue
        built = _taken_groups(store, change)

        # Merged units included, not just in-flight ones: a re-plan after some
        # units merged has to know they exist, or it either re-plans work that
        # is already in main or drops those groups — which the graph check then
        # rejects, leaving the change unplannable. Satisfied units too: they
        # never merge, but their groups are as done as a merged unit's.
        # Planned units of other changes too: the unstarted ones are what the
        # planner may join this change's groups to, or join to each other.
        # Merged and satisfied units of other changes are in the trunk and cannot affect a
        # plan: they are counted in one line, not listed.
        # Once a round: the plan check, the prompt and the figures stored all use one set.
        units = store.all()
        landed = {MERGED, SATISFIED}
        context = _plan_context(units, change)
        omitted = sum(1 for u in units if u.state in landed and u.change != change)
        ratios = calibrations(units)
        try:
            catalog = _task_catalog(inst)
            # The groups go in so the plan is checked against the tags, which
            # were validated on the change's own PR: a model handing one
            # repo's group to another repo's unit is a real failure mode.
            # Groups already accounted for by a unit nobody is going to
            # re-plan — merged, in flight, or failed or held and waiting for a
            # person — are passed as built:
            # without them the check demands every group appear in the new
            # plan, which makes a change unplannable the moment any part of
            # it starts.
            # Groups another change's planned unit carries are as claimed.
            plan = plan_round(
                calibrations=ratios,
                examples={
                    kind: recent_examples(
                        units, kind, config.active().global_limits.calibration_examples
                    )
                    for kind in ratios
                },
                changes={change: tasks.read_text()},
                in_flight=context,
                omitted=omitted,
                previous_refusal=_previous_refusal(planned.get(change), digest),
                groups=task_groups,
                built=built,
                # Units the store already has: a dependency naming one of
                # them is not a dependency on nothing.
                known={u.id for u in units},
                pins=_pins_of(units, change),
                context=JoinContext(
                    stored=tuple(units),
                    catalog=catalog,
                    needs={
                        group: tuple((need.change, need.group) for need in found)
                        for group, found in group_needs(tasks).items()
                    },
                ),
            )
            drops = _drop_cycle_edges(inst, store, change, plan.units, task_groups)
        except GroupTooLarge as error:
            # Fixed in tasks.md, not in the plan: every attempt is spent at
            # once, so the change waits for that edit instead of re-asking.
            failure = {
                "hash": digest,
                "sizing": _standing_sizing(planned.get(change), sizing),
                "attempts": max_attempts,
                "ok": False,
            }
            record_plans(inst, {change: failure | _refusal(error)})
            log(f"not planning {change}: {error}")
            results[change] = PlanResult(status="failed")
            continue
        except Exception as error:  # noqa: BLE001
            previous = record if record.get("hash") == digest else {}
            if (wait := _plan_wait(inst, error, previous)) is not None:
                kind, fields = wait
                # The plan that stands keeps the policy it was made under, so a change
                # waiting for an outage is still reported stale; only a change with no
                # earlier record takes the current one.
                record_plans(
                    inst,
                    {
                        change: {
                            "hash": digest,
                            "sizing": _standing_sizing(planned.get(change), sizing),
                            "ok": False,
                            **fields,
                        }
                    },
                )
                if kind == "network":
                    pause_until(
                        datetime.now(UTC) + PARK_BACKOFF[0],
                        reason=f"network unreachable while planning {change}",
                        marker=network_marker(inst.state_dir),
                        kind="network",
                    )
                log(
                    f"planning {change} is waiting for {PLAN_WAITS[kind]}, no attempt used — "
                    f"next try {_shown_time(fields['until']) or 'later'} — {fields['reason']}"
                )
                results[change] = PlanResult(status="waiting")
                # The rest would meet the same outage; the pause now stands and they are
                # planned on the tick that clears it. A replan asked for them, so it tries.
                network_down = network_down or (kind == "network" and not force)
                continue
            attempts = previous.get("attempts", 0) + 1
            failure = {
                "hash": digest,
                "sizing": _standing_sizing(planned.get(change), sizing),
                "attempts": attempts,
                "ok": False,
            }
            if isinstance(error, PlannerError):
                failure |= _refusal(error)
            else:
                failure["reason"] = _failure_reason(error)
            record_plans(inst, {change: failure})
            giving_up = (
                " — giving up until tasks.md changes or `abk replan` is run"
                if attempts >= max_attempts
                else " — `abk replan` plans it again now"
            )
            log(
                f"planning {change} failed ({attempts}/{max_attempts})"
                f"{giving_up} — {type(error).__name__}: {error}"
            )
            results[change] = PlanResult(status="failed")
            continue

        units = list(drops.units)
        for edge in drops.dropped:
            log(
                f"{edge.unit}: planner edge to {edge.dependency} dropped, it would close "
                f"the cycle {' -> '.join(edge.cycle)}"
            )
        if drops.cycle:
            log(
                f"{change}: cannot be ordered, a cycle of Needs: and stored dependencies: "
                f"{' -> '.join(drops.cycle)}"
            )
        before = {u.id: u for u in store.all()}
        try:
            store.upsert(units, change=change)
        except GroupOwned as error:
            # The cause is in the store, not in the model's answer: asking again would
            # propose the same plan, so every attempt is spent until tasks.md changes.
            for found in error.collisions:
                log(
                    f"not planning {change}: {found.change} group {found.group} is carried by "
                    f"{found.owner} ({found.owner_state.value}), so {found.claimant} cannot "
                    f"take it — run `abk retire {found.owner}`, or edit tasks.md to keep the "
                    f"group with {found.owner}"
                )
            failure = {
                "hash": digest,
                "sizing": _standing_sizing(planned.get(change), sizing),
                "attempts": max_attempts,
                "ok": False,
                "owned": sorted({found.owner for found in error.collisions}),
                "reason": _failure_reason(error),
            }
            record_plans(inst, {change: failure})
            results[change] = PlanResult(status="failed")
            continue
        planned_ids = {u.id for u in units}
        left_out = tuple(
            u.id
            for u in before.values()
            if u.change == change and u.state == PLANNED and u.has_work and u.id not in planned_ids
        )
        dropped = [join for join in plan.joins if not _write_join(inst, store, join, task_groups)]
        log(f"planned {change}: {len(units)} unit(s)")
        # After the joins, so a unit that took in more work is as urgent as its
        # most urgent group; a unit that has started keeps what it has.
        # Units that carry this change's groups from an earlier round are
        # visited too: an edited line reaches them without a join naming them.
        removed = {j.unit for j in plan.joins if j.unit}
        _set_priorities(
            store,
            [
                unit_id
                for unit_id in [
                    *(u.id for u in units),
                    *(j.onto for j in plan.joins),
                    *_carrying_unstarted(store, change),
                ]
                if unit_id not in removed
            ],
            catalog,
        )
        for unit_id in dict.fromkeys([*(u.id for u in units), *(j.onto for j in plan.joins)]):
            if unit_id not in removed:
                _record_calibration(store, unit_id, catalog, ratios)
        orphaned = _orphaned_changes(store, before)
        for other in sorted(orphaned):
            # The unit that carried this change's groups is gone, and nothing
            # else builds them: plan it again rather than leave them held by an
            # `unplanned` unit.
            log(f"{change}: {other} is planned again, the unit carrying its groups was dropped")
            planned.pop(other, None)
        if orphaned:
            record_plans(inst, {other: None for other in orphaned})
        if dropped:
            # A unit started while the plan was made. What was to be carried
            # is planned again next round, so this change is not recorded as
            # planned, and a record left by an earlier plan (a forced one
            # ignored it) is removed so the next tick does not skip it.
            record_plans(inst, {change: None})
            log(f"{change}: {len(dropped)} join(s) dropped, a unit started since the plan")
            results[change] = PlanResult(
                status="planned", dropped_joins=len(dropped), cycle=drops.cycle, kept=left_out
            )
            continue
        attempts_kept = record.get("attempts", 0) if record.get("waiting") else 0
        record_plans(
            inst,
            {
                change: {
                    "hash": digest,
                    "sizing": sizing,
                    "attempts": attempts_kept,
                    "ok": True,
                }
            },
        )
        results[change] = PlanResult(status="planned", cycle=drops.cycle, kept=left_out)
    if any(result.status == "planned" for result in results.values()):
        _promote(inst, store)
    return results


def _plan_context(units: Sequence[StoredUnit], change: str) -> list[dict]:
    """The units a plan of `change` is shown: those started, the planned ones of other changes,
    the unplanned ones of the change with what replaced them and its retired ids."""
    landed = {MERGED, SATISFIED}
    return [
        in_flight_item(u, units)
        for u in units
        if (u.state in _STARTED and (u.state not in landed or u.change == change))
        or (u.state == PLANNED and u.change != change)
        # Shown with what replaced it, so the planner knows its groups are carried.
        or (u.state == UnitState.UNPLANNED and u.superseded_by and u.change == change)
        # Shown so the planner leaves the id alone, though nothing is built on it.
        or (u.state == UnitState.RETIRED and u.change == change)
    ]


def _promote(inst: Installation, store: UnitStore) -> None:
    """Give each unstarted unit the urgency of the units that wait on it, and say which."""
    # A gated unit is left out of the round and lends nothing; the promotion is worked out
    # again every round, so it comes back in the first round that finds the hold gone.
    gated = split_gates(inst.config, inst.state_dir, store.all())
    for unit_id, priority, source in promote_ancestors(store, _task_catalog(inst), gated):
        log(f"promoted {unit_id} to priority {priority}, from {source}")


def _drop_cycle_edges(
    inst: Installation,
    store: UnitStore,
    change: str,
    plan_units: Sequence[Unit],
    groups: list[TaskGroup],
) -> CycleDrops:
    """The plan without the dependencies that would close a cycle with stored work, and
    its e2e stand-alone, acceptance and independence checks run again on what is left."""
    stored = store.all()
    # What the plan replaces covers no group: the plan's units do.
    kept = [
        u
        for u in stored
        if u.state not in BUILDS_NOTHING and not (u.change == change and u.state == PLANNED)
    ]
    drops = drop_cycle_edges(
        plan_units,
        stored,
        {
            unit_id: [found.target for found in found_needs]
            for unit_id, found_needs in declared_needs(inst, [*kept, *plan_units]).items()
        },
    )
    if drops.dropped:
        check_flagged_groups(list(drops.units), groups)
    return drops


def _record_calibration(
    store: UnitStore,
    unit_id: str,
    catalog: dict[str, tuple[TaskGroup, ...]],
    ratios: dict[Kind, Calibration],
) -> None:
    """Fix an unstarted unit's flag and calibrated figure as it is planned, from its own
    estimate and its kind's ratio; with calibration off there is no figure."""
    unit = store.get(unit_id)
    kind = plan_kind(unit, catalog.get(unit.change))
    on = config.active().global_limits.calibrate_estimates
    figure = calibrated(unit.estimated_lines, applied(ratios, kind).ratio) if on else None
    store.set_calibration(unit_id, kind.flag, figure or None)


def _orphaned_changes(store: UnitStore, before: dict[str, StoredUnit]) -> set[str]:
    """Changes whose groups a unit just demoted to `unplanned` was carrying."""
    return {
        member.change
        for unit in store.all()
        if unit.state == UNPLANNED and before.get(unit.id) and before[unit.id].state != UNPLANNED
        for member in unit.joined
    }


def _write_join(
    inst: Installation, store: UnitStore, join: Join, task_groups: Sequence[TaskGroup]
) -> bool:
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
            kinds = [g.tier for g in task_groups if g.number in join.groups]
            estimates = store.join(join, group_kinds=kinds)
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
def specification(tasks: Path) -> str:
    """A change's tasks with progress and `Needs:` lines stripped out: what a re-plan keys on."""
    return specification_text(tasks.read_text())


def plan_digest(tasks: Path, recorded: str | None = None) -> str:
    """The hash a change's plan record keeps: a re-plan happens when this one moves.

    It ignores the spelling of the test-kind tags. `recorded` is the hash the plan record holds:
    when it is the hash of this text in the earlier spelling, it is returned, so a plan made
    before the rename counts as current for the same text after `abk tags --fix`."""
    return text_digest(tasks.read_text(), recorded)


def text_digest(text: str, recorded: str | None = None) -> str:
    """`plan_digest` of a tasks file's text."""

    def hashed(spell: Callable[[str], str]) -> str:
        return hashlib.sha256(specification_text(text, spell).encode()).hexdigest()

    # An earlier release hashed the text as written: every tag old, or the two spellings mixed.
    if recorded is not None and recorded in (hashed(old_tag), hashed(lambda tag: tag)):
        return recorded
    return hashed(current_tag)


# Units that still need a tick: being built, waiting to be, or open for review
# (whose CI, comments and merge only a poll notices). Merged and closed are
# done; failed and held wait for a person, and a tick changes nothing for them.
NEEDS_TICKS = (PLANNED, RUNNING, IN_REVIEW)


def has_work(inst: Installation, store: UnitStore) -> bool:
    """Whether a tick has anything to do: a unit in progress, a change
    whose tasks.md has not been planned in its current form, a change with
    a satisfied unit that is ready to archive and not yet verified, or a repo
    that is due for its scheduled e2e-test run and has no such change open.

    The last is the one a poll cannot notice: a merge is found at the top of a
    tick and archived in it, but a unit ends satisfied inside the scheduling
    step, after that. A failed verification is on record, so it does not keep
    ticks busy.
    """
    units = store.all()
    if any_due(inst, store, today=spans.clock.now().date()):
        return True
    if any(
        unit.state in NEEDS_TICKS
        or _awaiting_split(unit)
        or unit.close_pending
        or (unit.state == FAILED and unit.cause is Cause.ENVIRONMENT)
        for unit in units
    ):
        return True
    satisfied = [u for u in units if u.state == SATISFIED]
    if satisfied:
        record = VerifyRecord(inst.state_dir / "verified.json")
        waiting = set(_unverified(inst, units, record))
        if any(m.change in waiting for u in satisfied for m in u.members()):
            return True
    planned = planned_hashes(inst)
    for tasks in inst.tasks_files():
        record = planned.get(tasks.parent.name) or {}
        digest = plan_digest(tasks, record.get("hash"))
        if record.get("hash") != digest or not record.get("ok"):
            return True
    return False


def planned_hashes(inst: Installation) -> dict[str, dict]:
    """What has been planned, and what failed to plan, keyed by change.

    Machine-local and safe to lose: `upsert` merges by unit id and keeps
    state, branch and PR, so a forgotten record costs one model call.
    """
    try:
        loaded = json.loads((inst.state_dir / "planned.json").read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in loaded.items() if isinstance(v, dict)}


def sizing_digest() -> str:
    """A digest of the policy the active workspace plans under, in two parts joined by a dot so a
    difference can be told apart: the ceilings (every tier's, each repo's own, `min_unit_lines`
    and `max_unit_lines`), then the rest of the `review` section. Empty while `review.enabled`
    is false."""
    workspace = config.active()
    if not workspace.review.enabled:
        return ""

    def digest(part: object) -> str:
        return hashlib.sha256(json.dumps(part, sort_keys=True).encode()).hexdigest()

    ceilings = {
        "review": workspace.review.ceilings.model_dump(mode="json"),
        "repos": {
            name: repo.review.ceilings.model_dump(mode="json")
            for name, repo in workspace.repos.items()
        },
        "min_unit_lines": workspace.global_limits.min_unit_lines,
        "max_unit_lines": workspace.global_limits.max_unit_lines,
    }
    rest = {
        "review": workspace.review.model_dump(mode="json", exclude={"ceilings"}),
        "repos": {
            name: repo.review.model_dump(mode="json", exclude={"ceilings"})
            for name, repo in workspace.repos.items()
        },
    }
    return f"{digest(ceilings)}.{digest(rest)}"


def plan_is_stale(record: Mapping[str, Any], current: str | None = None) -> bool:
    """Whether a recorded plan was made under a policy other than the current one (`current`, or
    `sizing_digest()` when it is not given). A record with no `sizing` reads as the empty digest."""
    return record.get("sizing", "") != (sizing_digest() if current is None else current)


def plan_stale_reason(record: Mapping[str, Any], current: str | None = None) -> str:
    """Why a stale plan is stale: it predates the review policy, the policy was turned off, the
    ceilings changed, the rest of the `review` section changed, or both did."""
    now = sizing_digest() if current is None else current
    was = record.get("sizing", "")
    if not was:
        return "planned before the review policy"
    if not now:
        return "the review policy was turned off"
    old, new = was.split("."), now.split(".")
    if len(old) != 2:
        return "the review policy changed"
    changed = [
        name
        for name, before, after in zip(("ceilings", "review section"), old, new, strict=True)
        if before != after
    ]
    return " and ".join(f"the {name} changed" for name in changed) or "the review policy changed"


def _plan_stands(record: Mapping[str, Any], has_units: bool) -> bool:
    """Whether a recorded plan is one whose units stand: it succeeded, or it waits for an
    outage while the change still has stored units."""
    return bool(record.get("ok") or (record.get("waiting") in PLAN_WAITS and has_units))


def stale_plan_lines(inst: Installation) -> list[str]:
    """One line for each change whose standing plan was made under another policy, naming the
    change and why, and saying how to plan it again."""
    records = planned_hashes(inst)
    current = sizing_digest()
    standing = {unit.change for unit in store_for(inst).all()}
    return [
        f"{change}: plan is stale, {plan_stale_reason(record, current)} "
        f"— `abk replan {change}` plans it again"
        for change in (path.parent.name for path in inst.tasks_files())
        if (record := records.get(change))
        and _plan_stands(record, change in standing)
        and plan_is_stale(record, current)
    ]


def record_plans(inst: Installation, updates: Mapping[str, dict | None]) -> None:
    """Set (or, for None, remove) recorded plans by change, under a lock, atomically."""
    update_plans(inst, lambda _: updates)


def update_plans(
    inst: Installation, updates: Callable[[dict[str, dict]], Mapping[str, dict | None]]
) -> None:
    """Set (or, for None, remove) recorded plans by change, as `updates` says of the
    records read under the lock, atomically.

    Read, changed and written whole under one lock, and the file replaced in one
    step, so a command beside a planning pass loses neither's update.
    """
    path = inst.state_dir / "planned.json"
    with file_lock(inst.state_dir / "planned.lock"):
        records = planned_hashes(inst)
        for change, record in updates(records).items():
            if record is None:
                records.pop(change, None)
            else:
                records[change] = record
        atomic_write_text(path, json.dumps(records, indent=2) + "\n")


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
        if not has_origin(path):
            continue
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

    restack: Restack
    remove_worktree: Callable[..., None]
    delete_branch: Callable[..., None]
    claim: Callable[[StoredUnit], AbstractContextManager[object]]
    retarget: Callable[[StoredUnit, str], None]
    rebase_cap: int | None
    resume: Callable[..., bool]
    lane: Lane | None


def gated_resolver(
    unit_id: str,
    refused: Callable[[str, datetime | None], None] | None = None,
    account: claude_account.Account | None = None,
) -> ConflictSession:
    """A conflict resolver that asks the usage guard before each call, as a unit's agent step
    does, naming `unit_id` so an admission on an estimate is kept under it and judged on the
    windows of `account`, the unit's own. A refusal is raised
    as the model's own, which the move answers by aborting the rebase, and `refused` is told
    when the guard expects to allow it again."""
    may_start, resume_at = build_usage_gate(account=account)

    class Gated(ConflictSession):
        def __call__(self, prompt: str, *, cwd: Path, follow_up: str = "") -> None:
            try:
                ask_before_call(unit_id, may_start, resume_at)
            except AgentRateLimited as error:
                if refused is not None:
                    refused(unit_id, error.resets_at)
                raise
            super().__call__(prompt, cwd=cwd, follow_up=follow_up)

    return Gated()


def build_turned_move(
    installation: Installation,
    *,
    gated: bool = False,
    refused: Callable[[str, datetime | None], None] | None = None,
) -> Callable[..., Moved]:
    """The move of a branch onto a base, told which repo's settings apply and holding that
    repo's turn only for the phases that write what its worktrees share. With `gated`, the
    conflict resolver is asked of the usage guard first, and `refused` hears of a refusal."""
    names = {path: repo for repo, path in installation.checkouts.items()}

    def move(path: Path, *args, **kwargs) -> Moved:
        name = names[path]
        if gated and "resolve" not in kwargs:
            kwargs["resolve"] = gated_resolver(
                kwargs["moving_unit"],
                refused,
                claude_account.for_repo(installation.config, name),
            )
        return resolved_move(
            path,
            *args,
            repo_config=installation.repo(name),
            turn=partial(repo_turn, installation, name),
            **kwargs,
        )

    return move


def build_restack_lane(inst: Installation, store: UnitStore) -> RestackLanes:
    """The tick's lanes, one for each project: each has `project_limits.max_concurrent_restacks`
    workers apart from the build workers, moving a unit onto the base it has when it starts."""

    refusals: set[str] = set()

    def refused(unit_id: str, resume_at: datetime | None) -> None:
        refusals.add(unit_id)
        lanes.defer_until(unit_id, resume_at)

    moves = build_stack_moves(store, inst, gated=True, refused=refused)
    move = build_turned_move(inst, gated=True, refused=refused)

    def run_of(unit_id: str) -> Rest:
        """What remains of a moved-base run once the move is made: the unit's own run, here in
        the lane's worker, flagged as the lane's so a build worker never resumes it."""

        def run() -> None:
            if unit_id in refusals:
                # The guard refused the move's agent: the lane moves it again when it allows.
                refusals.discard(unit_id)
                return
            if Leases(lease_dir(inst.state_dir)).holder(unit_id) is not None:
                raise BranchBusy(f"a tab holds the lease of {unit_id}")
            if branch_is_held(inst, store.get(unit_id).branch or branch_name(store.get(unit_id))):
                raise BranchBusy(f"the branch of {unit_id} is held by another run")
            # The run flags itself once it holds the branch and the unit is runnable.
            build_unit(
                inst,
                store.get(unit_id),
                store=store,
                moved_base_run=True,
                # A pause that stopped the run: the lane tries it again from the guard's time.
                on_pause=lambda resume_at: lanes.defer_until(unit_id, resume_at),
            )

        return run

    def move_unit(owed: StoredUnit) -> Rest | None:
        unit = store.get(owed.id)
        refusals.discard(unit.id)  # A refusal belongs to the one move that met it.
        if in_a_lane_run(unit):
            return run_of(unit.id)  # An interrupted run: its thread resumes at its node.
        graph = store.all()
        if hold_if_spent(inst, store, unit, graph, log):
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
        if has_thread(inst, unit.id):
            # Parked at `prepare`: the lane makes the move here, and its worker goes on into
            # the unit's run (`run_of`).
            try:
                ended = advance_thread_through_prepare(inst, unit, store=store)
            except AgentRateLimited as error:
                # The guard refused the resolver: the move is tried again when it allows.
                lanes.defer_until(unit.id, error.resets_at)
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
        if worktree_path(repo, branch, inst.worktree_root).exists():
            store.set_state(
                unit.id,
                RUNNING,
                note=f"restack onto {new_base} left for its run, not a conflict: "
                "its worktree has the branch checked out",
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
                temporary_root=inst.worktree_root,
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

    def stamp(owed: StoredUnit) -> tuple[str, str]:
        """The heads a restack of the unit depends on: its branch and the base it moves onto."""
        unit = store.get(owed.id)
        repo = inst.checkouts[unit.repo]
        base = local_ref(base_of(unit, store.all()), repo=unit.repo)
        heads = [
            git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).stdout.strip()
            for ref in (unit.branch or branch_name(unit), base)
        ]
        return heads[0], heads[1]

    def make(key: ProjectKey) -> RestackLane:
        return RestackLane(
            inst.max_concurrent_restacks,
            move=move_unit,
            claim=moves["claim"],
            stamp=stamp,
            # One key for each pause in force: an account's, or the network's.
            paused=lambda: [
                (each.kind == "network", each.account) for each in pauses_in_force(inst.state_dir)
            ],
            record=record_path(inst.state_dir, key),
            base=lambda owed: base_of(owed, store.all()),
            runs=in_a_lane_run,
            log=log,
        )

    lanes = RestackLanes(make, owed=lambda units: owed_units(inst, units))
    return lanes


def build_stack_moves(
    store: UnitStore,
    installation: Installation,
    *,
    lane: Lane | None = None,
    gated: bool = False,
    refused: Callable[[str, datetime | None], None] | None = None,
) -> StackMoves:
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

    move = build_turned_move(installation, gated=gated, refused=refused)

    def checkout(path: Path, branch: str, **kwargs):
        """A checkout of the branch at a given head, made and removed in the repo's turn."""
        return checked_out_at(
            path, branch, turn=partial(repo_turn, installation, names[path]), **kwargs
        )

    def unit_test_of(*, cwd: Path, base: str, moved_from: str | None = None) -> tuple[bool, str]:
        """Unit-test as the repo whose checkout, or worktree of it, `cwd` is builds it."""
        for name, path in checkouts.items():
            if cwd == path or cwd.parent == installation.worktree_root / path.name:
                repo = installation.repo(name)
                return build_unit_test(
                    profile=profiles.get(repo.profile),
                    root_extras=repo.tests.root_extras,
                    projects=repo.projects,
                    repo=repo,
                    log=log,
                )(cwd=cwd, base=base, moved_from=moved_from)
        raise ValueError(f"{cwd} is not a checkout of any repo or a worktree of one")

    return {
        "restack": build_restack(
            repos=checkouts,
            store=store,
            root=installation.worktree_root,
            posts_root=installation.state_dir,
            move=move,
            checkout=checkout,
            unit_test=unit_test_of,
            on_flake=build_on_flake(store, installation, log=log),
            push=at_path(push_with_lease),
        ),
        "remove_worktree": named(build_remove_worktree(checkouts, root=installation.worktree_root)),
        "delete_branch": named(build_delete_branch(checkouts)),
        "claim": build_claim(installation.state_dir / "locks"),
        "retarget": build_retarget(),
        "rebase_cap": installation.stack_depth_rebase_cap,
        "lane": lane,
        "resume": lambda unit, kind, reason, feedback, from_person=False, rework=None: (
            resume_thread(
                installation,
                unit,
                kind,
                store=store,
                reason=reason,
                feedback=feedback,
                from_person=from_person,
                rework=rework,
            )
            is not None
        ),
    }


def _dispatch(
    inst: Installation,
    store: UnitStore,
    say: Callable[[str], None] = log,
    *,
    lane: Lane | None = None,
) -> Callable[..., bool]:
    """What each poller event is handed to, every write to a repo's `.git` in
    that repo's turn. Also how a merge the poll has not reported yet is recorded."""
    return build_dispatch(
        store,
        # A lane moves what the handlers hand it, and asks the guard before its resolver.
        **build_stack_moves(
            store,
            inst,
            lane=lane,
            gated=lane is not None,
            refused=lane.defer_until if lane is not None else None,
        ),
        base_tip=build_base_tip(store, inst.checkouts),
        fork_point=build_fork_point(store, inst.checkouts),
        paused=lambda unit: _paused_for(inst, unit) is not None,
        fetch_review=build_fetch_review(
            extra_notes=ui_notes_of(inst, store), patch_of=unit_patch_of(inst, store)
        ),
        fetch_checks=build_fetch_check_logs(),
        rerun_checks=build_rerun_checks(),
        # A pass polls between builds, so an event may name a unit still
        # building; the handlers leave it to a later poll. See `events`.
        waiting_path=inst.state_dir / "held-waiting.json",
        landing_path=inst.state_dir / landing_intent.LANDING,
        merge_record=lambda unit: _merge_record(inst, unit),
        log=say,
    )


def _merge_record(inst: Installation, unit: StoredUnit) -> tuple[str | None, int | None]:
    """The merge commit of a unit just seen merged and the number of the tick that saw it;
    None for what cannot be read (a forge that answers nothing, no tick record yet)."""
    sha = None
    if unit.pr is not None:
        try:
            forge, repo_id = inst.forge_of(unit.repo)
            sha = forge.merge_commit(repo_id, unit.pr)
        except Exception as error:  # noqa: BLE001 — a merge is recorded without its commit.
            log(f"{unit.id}: merge commit unknown — {error}")
    record = loaded_code.current()
    return sha, record.number if record else None


def deliver_hold_event(
    inst: Installation,
    store: UnitStore,
    event: str,
    unit: StoredUnit,
    *,
    say: Callable[[str], None],
) -> bool:
    """Hand a `hold` or `release` for the unit's pull request to the poller's own dispatch,
    with its branch claim and thread delivery. False when the unit is being built and the
    event was deferred; what the handler reports goes to `say`."""
    if unit.pr is None:
        say(f"{unit.id} has no pull request")
        return False
    return _dispatch(inst, store, say)(event, unit.pr, repo=unit.repo)


def hold_label_on(inst: Installation, unit: StoredUnit) -> bool:
    """Whether the last poll saw the hold label on the unit's pull request."""
    recorded = PrState.load(state_path(inst.state_dir, unit.repo))
    return HOLD_LABEL in (recorded.get(str(unit.pr)) or {}).get("labels", [])


def _ui_review_of(
    inst: Installation, store: UnitStore, repo: str, pull: PullRequest
) -> Review | None:
    """The review made in the web UI of the unit whose pull request `pull` is."""
    unit = unit_of(store, repo, pull.number)
    return ReviewStore(inst.state_dir / "reviews").read(unit.id) if unit else None


def poll_all(inst: Installation, *, store: UnitStore, lane: Lane | None = None) -> None:
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
    restack's unit-test run happens outside the turn: it writes nothing to
    `.git`, and holding the turn through it would keep every build in the
    repo waiting on a test run as well.
    """
    checkouts = inst.checkouts

    dispatch = _dispatch(inst, store, lane=lane)

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
            list_prs=with_ui_review(
                lambda forge=forge, repo_id=repo_id: forge.list_prs(repo_id),
                review_of=lambda pull, repo=repo: _ui_review_of(inst, store, repo, pull),
            ),
            unit_of=lambda number, repo=repo: unit_of(store, repo, number),
            ignore=lambda number, slug=slug: ignored(inst.state_dir, slug, number),
            human_activity=lambda number, repo=repo: _note_human_activity(store, repo, number),
            consume=lambda number, name, repo=repo: labels.consume(repo, number, name),
            log=log,
        ).poll()
        _refresh_check_labels(inst, store, repo, labels)
    _refresh_graph_page(inst, store)


def _note_human_activity(store: UnitStore, repo: str, number: int) -> None:
    """Stamp the unit whose pull request a person has answered, once."""
    if unit := unit_of(store, repo, number):
        store.mark_human_activity(unit.id)


def _refresh_graph_page(inst: Installation, store: UnitStore) -> None:
    """Rewrite the graph page after a poll: the checks it shows may have changed
    with no store write. An unchanged body is skipped. A view, so it never fails the poll."""
    try:
        units = store.all()
        diagram.write_page(
            units,
            inst.graph_page,
            checks_of=recorded_checks(inst.state_dir),
            paused=parked_units(inst, units),
            restacking=restacking_bases(inst),
            projects=declared_projects(inst.repos),
        )
    except Exception as error:  # noqa: BLE001
        log(f"graph not refreshed — {type(error).__name__}: {error}")


def _refresh_check_labels(
    inst: Installation, store: UnitStore, repo: str, labels: StateLabels
) -> None:
    """Bring the state label of each unit in review in line with what its checks
    now make of it. A stored state change moves the label by itself; a poll of
    checks does not, so it is done here, only where a state label is already
    on the pull request."""
    units = store.all()
    checks_of = recorded_checks(inst.state_dir)
    recorded = PrState.load(state_path(inst.state_dir, repo))
    names = state_label_names()
    for unit in units:
        if unit.repo != repo or unit.state != IN_REVIEW or unit.pr is None:
            continue
        shown = effective_state(unit, units, checks_of=checks_of)
        carried = names & set((recorded.get(str(unit.pr)) or {}).get("labels", []))
        label = state_label(shown)
        if carried and label is not None and carried != {label.name}:
            labels.set_state(repo, unit.pr, shown)


class _Run:
    """How a unit's run ended, for its span and its duration: the run's status,
    or why it did not get as far as one."""

    outcome = UnitOutcome.INTERRUPTED


def _outage_cause(inst: Installation, error: NetworkUnavailable) -> Cause | None:
    """The cause a unit parks with for `error`, or None when the run failed for another
    reason. A strong sign is evidence enough; a weak one parks as the probe sorts it."""
    if error.strength == "strong":
        return Cause.NETWORK_UNAVAILABLE
    limits = inst.config.global_limits
    return network_probe.classify_reachability(
        error.host,
        network_probe.control_group(inst),
        timeout=limits.network_probe_timeout_seconds,
        api_port=error.port,
    )


def build_unit(
    inst: Installation,
    unit: Unit,
    *,
    store: UnitStore,
    queued: spans.Mark | None = None,
    moved_base_run: bool = False,
    on_pause: Callable[[datetime | None], None] | None = None,
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
                inst,
                unit,
                store=store,
                run=run,
                trace=telemetry.reference(span),
                queued=queued,
                moved_base_run=moved_base_run,
                on_pause=on_pause,
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
                log,
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
        at = stamp()
        log(f"{unit.id}: {message}", at=at)
        if run_log is not None:
            run_log.emit(f"[{at}] {message}")

    def journal_only(message: str) -> None:
        log(f"{unit.id}: {message}", at=stamp())

    def unit_log_only(message: str) -> None:
        if run_log is not None:
            run_log.emit(f"[{stamp()}] {message}")

    def end(message: str, outcome: UnitOutcome) -> None:
        nonlocal ended
        ended = message
        run.outcome = outcome
        say(message)

    def park(error: Exception, cause: Cause) -> None:
        """The work is fine and the thread stays at the step: the unit is `planned` with
        `cause`, and the pass readmits it after a backoff, resuming at that step."""
        end(f"parked, {error}", UnitOutcome.INTERRUPTED)
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
                    end("skipped, it was joined into another unit", UnitOutcome.SKIPPED)
                    return True
                # A unit may also be `running`: killed or paused in a node,
                # which is how its thread resumes it.
                # A moved-base run may start from a unit still in review that was sent back
                # for its conflict.
                sent_back = (
                    moved_base_run and unit.state == IN_REVIEW and unit.sent_back_for_conflict
                )
                if unit.state not in (PLANNED, RUNNING) and not sent_back:
                    end(f"skipped, it is now {unit.state}", UnitOutcome.SKIPPED)
                    return True
                # A tab may have taken the lease since the pass picked this unit. The
                # server writes the lease and then reads the branch lock; this takes the
                # lock and then reads the lease, so one of the two always sees the other.
                if Leases(lease_dir(inst.state_dir)).holder(unit.id) is not None:
                    end("skipped, a tab holds its lease", UnitOutcome.SKIPPED)
                    return True
                if moved_base_run:
                    # The lane's run: flagged only now that it holds the branch and may go on.
                    # A run that starts is an attempt at its base's tip; one resumed is not,
                    # unless the start it resumes stopped before its first agent call.
                    if not unit.moved_base_run or unit.moved_base_uncounted:
                        tip = base_tip(inst, unit, store.all())
                        if not tip:
                            end("skipped, its base cannot be read", UnitOutcome.SKIPPED)
                            return True
                        before = unit
                        record_run_attempt(store, unit, tip)
                    store.set_moved_base_run(unit.id, True)
                    store.set_moved_base_uncounted(unit.id, False)
                # A step recorded by an earlier run belongs to that run. A parked unit, or one
                # the restack lane handed back, resumes at its node, which never passes
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
                runner = build_runner(
                    unit,
                    store=store,
                    installation=inst,
                    record_merge=lambda repo, pr: _dispatch(inst, store)("merged", pr, repo=repo),
                    log=say,
                    log_reaches_run_log=True,
                    journal=journal_only,
                    transcript=agent_said,
                )
                outcome = run_unit_thread(
                    inst, runner, unit, base=base, graph=graph, run_log=run_log, lane=moved_base_run
                )
                if outcome.handed_back:
                    # Not moved-base work: a build worker takes the unit from the step its
                    # thread stands at. Leaving `running` clears the lane's flag.
                    store.set_state(
                        unit.id, PLANNED, note=outcome.handed_back, cause=Cause.RESTACK_HANDED_BACK
                    )
                    end(f"handed back — {outcome.handed_back}", UnitOutcome.INTERRUPTED)
                    return True
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
                marker=_paused_marker(inst, refused_account),
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
            if (cause := _outage_cause(inst, error)) is None:
                fail(error)
                return True
            park(error, cause)
            return True
        except Exception as error:  # noqa: BLE001 — see the docstring.
            fail(error)
            return True

        end(f"{outcome.status} — {outcome.detail}", outcome.status)
        if outcome.status is UnitOutcome.PAUSED:
            forget_if_not_begun()
            if on_pause is not None:
                on_pause(outcome.pause.until if outcome.pause else None)
            emit_metric(
                "count", "abk.usage.pauses", 1, say, unit=unit.id, change=unit.change, kind="usage"
            )
            _pause_for_usage(
                inst,
                outcome.pause or PauseInfo(reason=outcome.detail),
                claude_account.for_repo(inst.config, unit.repo),
            )
        return True
    finally:
        if run_log is not None:
            run_log.close(ended)


def _pause_for_usage(inst: Installation, pause: PauseInfo, account: claude_account.Account) -> None:
    """Pause the pipeline for a run the usage guard stopped.

    Re-read rather than reuse the tick's reading: the guard said no after the
    units before this one ran, so the window has moved, and a resume scheduled
    from the stale figure wakes up into a full window. The guard's own answer
    to when, which counts the ramp towards the reset — not the reset itself,
    which it can be well before. A pause that names its own time keeps it.
    """
    until = pause.until or build_resume_at(start=lambda: _start_decision([account]))()
    state = pause_until(
        until, reason=pause.reason, marker=_paused_marker(inst, account), account=account.label
    )
    log(_pause_report(inst, state, verb="pausing"))


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
    lane: bool = False,
) -> RunOutcome:
    """Start or resume the unit's thread to its next wait or the end; with `lane`, as the
    restack lane's run, which stops before work that is not about the move."""
    return asyncio.run(
        _on_thread(inst, runner, unit, base=base, graph=graph, run_log=run_log, lane=lane)
    )


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
    lane: bool = False,
) -> RunOutcome:
    """Start or resume the unit's thread to its next wait, or deliver `event` to it."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
    from agent_build_kit.graph.unit import resume_unit, run_unit

    common = dict(base=base, graph=graph, run_log=run_log, tracer=telemetry.tracer())
    async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
        if event is None:
            # Under the lock `build_unit` holds; a delivery takes its own.
            return await run_unit(runner, unit, saver=saver, lane=lane, **common)
        return await resume_unit(
            runner,
            unit,
            saver=saver,
            event=event,
            feedback=feedback,
            locks=inst.state_dir / "locks",
            **common,
        )


def _unit_log(unit: StoredUnit) -> Callable[[str], None]:
    def say(message: str) -> None:
        log(f"{unit.id}: {message}")

    return say


def _thread_runner(
    inst: Installation, unit: StoredUnit, store: UnitStore, say: Callable[[str], None]
) -> tuple[Callable[[], UnitRunner], str, list[StoredUnit]]:
    """What a thread is run with away from a build slot: a way to make its runner, the base it
    builds on and the graph it is read against."""
    graph = store.all()

    def make_runner() -> UnitRunner:
        return build_runner(
            unit,
            store=store,
            installation=inst,
            record_merge=lambda repo, pr: _dispatch(inst, store)("merged", pr, repo=repo),
            log=say,
        )

    return make_runner, base_of(unit, graph), graph


def advance_thread_through_prepare(
    inst: Installation, unit: StoredUnit, *, store: UnitStore
) -> UnitRun | None:
    """Run the unit's thread through `prepare` and no further, the move onto its moved base
    that `prepare` makes, leaving the thread for a build slot; the state it ends in. None when
    the thread is not parked at `prepare`. The caller holds the unit's branch."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
    from agent_build_kit.graph.unit import advance_through_prepare

    make_runner, base, graph = _thread_runner(inst, unit, store, _unit_log(unit))

    async def advance() -> UnitRun | None:
        async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
            return await advance_through_prepare(
                make_runner, unit, base=base, graph=graph, saver=saver, tracer=telemetry.tracer()
            )

    return asyncio.run(advance())


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
    requeue: RequeueReason | None = None,
    rework: ReworkKind | None = None,
    guidance: str = "",
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
        feedback_source=feedback_source_of(rework),
        guidance=guidance,
        requeue=requeue,
        rework=rework,
    )
    say = _unit_log(unit)
    try:
        make_runner, base, graph = _thread_runner(inst, unit, store, say)
        runner = make_runner()
        store.record_step(unit.id, "")
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
            store.set_state(
                unit.id,
                UnitState.FAILED,
                note=f"{type(error).__name__}: {error}",
                cause=Cause.FAILED,
            )
        except Exception as second:  # noqa: BLE001
            say(f"could not be recorded as failed — {second}")
        say(detail)
        return Resumed(outcome=RunOutcome(status=RunStatus.FAILED, detail=detail), raised=True)
    say(f"{event.kind.value} delivered: {outcome.status} — {outcome.detail}")
    return Resumed(outcome=outcome)


# --- tags / gate / check / archive / openspec ----------------------------------------


def _is_text(path: Path) -> bool:
    """Whether `path` reads as text; a file that does not is left out of the cycle check and
    is reported for itself where it is selected."""
    try:
        path.read_bytes().decode()
    except (UnicodeDecodeError, OSError):
        return False
    return True


def _needs_cycle_problems(inst: Installation) -> dict[str, str]:
    """The message for each change that has a `Needs:` line on a cycle of the changes' groups."""
    cycle = needs_cycle([path for path in inst.tasks_files() if _is_text(path)])
    if not cycle:
        return {}
    chain = " -> ".join(f"{change} group {group}" for change, group in cycle)
    crossing = {
        before[0] for before, after in zip(cycle, cycle[1:], strict=False) if before[0] != after[0]
    }
    return {change: f"{change}: Needs: cycle {chain}" for change in crossing}


def _validated(inst: Installation, path: Path) -> tuple[list[TaskGroup], list[ValidationError]]:
    """A tasks file's groups and errors against the installation's repos and their projects."""
    return validate_tasks(
        path,
        repos=tuple(inst.repos),
        projects=declared_projects(inst.repos),
        splits=declared_split_names(inst.repos, inst.config),
    )


def _tag_warnings(inst: Installation, path: Path) -> list[str]:
    """What `abk tags` and `abk check` warn of in a tasks file, none of it a problem."""
    return [
        *cross_repo_needs_notes(
            path,
            inst.changes_dir,
            repos=tuple(inst.repos),
            projects=declared_projects(inst.repos),
        ),
        *old_test_kind_warnings(path),
        *redundant_separate_warnings(path),
        *product_path_warnings(path, _validated(inst, path)[0], inst.repos),
        *manual_runbook_warnings(path, inst.root),
        *inverted_group_warnings(
            path,
            inst.changes_dir,
            repos=tuple(inst.repos),
            projects=declared_projects(inst.repos),
        ),
        *unrelated_parent_warnings(
            path,
            inst.changes_dir,
            repos=tuple(inst.repos),
            projects=declared_projects(inst.repos),
        ),
    ]


def _rehashed(records: Mapping[str, dict], change: str, read: str, written: str) -> dict[str, dict]:
    """The update that moves `change`'s plan record to the hash of `written`, when the record is
    current for `read`, the text before the rewrite; nothing otherwise."""
    record = records.get(change)
    recorded = record.get("hash") if record else None
    if record is None or recorded is None or text_digest(read, recorded) != recorded:
        return {}
    return {change: record | {"hash": text_digest(written)}}


def _fix_change_tags(
    inst: Installation, change: str, cycles: Mapping[str, str], *, dry_run: bool
) -> bool:
    """Rewrite the old test-kind tags of one change's tasks.md and print what happened; whether
    it was handled, and not refused. A change is written only when the rewritten text parses to
    the same groups and the original had no other tag problem."""
    path = tasks_path(change, inst.changes_dir)

    def refuse(reason: str) -> bool:
        print(f"{change}: refused, {reason}")
        return False

    if not path.is_file():
        return refuse(f"no tasks.md at {path}")
    # Read and replaced under the lock a tick holds to tick the boxes, so neither loses the
    # other's write.
    with file_lock(path.with_name(f"{path.name}.lock")):
        try:
            text = path.read_bytes().decode()
        except UnicodeDecodeError:
            return refuse(f"{path} is not valid text")
        except OSError as exc:
            return refuse(f"could not read {path}: {exc}")
        before, errors = _validated(inst, path)
        if change.lower() in cycles:
            print(cycles[change.lower()])
            return refuse(f"a Needs: cycle, run `abk tags {change}`")
        if errors:
            for error in errors:
                print(f"{path}:{error}")
            return refuse(f"{len(errors)} other problem(s), run `abk tags {change}`")
        fixed, count = retag_headings(text, current_tag)
        if not count:
            print(f"{change}: unchanged")
            return True
        with tempfile.TemporaryDirectory() as scratch:
            probe = Path(scratch) / change / "tasks.md"
            probe.parent.mkdir()
            probe.write_bytes(fixed.encode())
            after, after_errors = _validated(inst, probe)
        if (before, []) != (after, after_errors):
            return refuse("the rewritten tags do not parse to the same groups; nothing written")
        if not os.access(path, os.W_OK):
            return refuse(f"{path} is read-only")
        if dry_run:
            print(f"{change}: would rewrite {count} tag(s)")
            return True
        try:
            atomic_write_bytes(path, fixed.encode())
        except OSError as exc:
            return refuse(f"could not write {path}: {exc}")
        # A plan that stood before the rewrite stands after it: keep the record's other fields
        # and move its hash to the rewritten text, whatever mix of spellings it hashed. Judged
        # under the plans lock, against the record as it is and the text that was read.
        update_plans(inst, lambda records: _rehashed(records, change, text, fixed))
    print(f"{change}: rewrote {count} tag(s)")
    return True


def cmd_tags(args: argparse.Namespace, inst: Installation) -> int:
    """Validate a change's task-group tags (or every change's), or with `--fix` rewrite the old
    test-kind tags of the open changes."""
    fix = getattr(args, "fix", False)
    command = "abk tags --fix" if fix else "abk tags"
    if getattr(args, "dry_run", False) and not fix:
        print("abk tags: --dry-run needs --fix", file=sys.stderr)
        return 2
    if args.all and args.change:
        print(f"{command}: give a change or --all, not both", file=sys.stderr)
        return 2
    if not args.all and not args.change:
        print(f"{command}: name a change, or pass --all for every change", file=sys.stderr)
        return 2
    changes = [t.parent.name for t in inst.tasks_files()] if args.all else [args.change]
    if not changes:
        # Silence reads as a failure; an empty store is a normal state.
        print(f"no changes in {inst.changes_dir}")
        return 0
    if fix:
        dry_run = getattr(args, "dry_run", False)
        cycles = _needs_cycle_problems(inst)
        handled = [_fix_change_tags(inst, change, cycles, dry_run=dry_run) for change in changes]
        return 0 if all(handled) else 1
    failed = 0
    cycles = _needs_cycle_problems(inst)
    for change in changes:
        groups, errors = check_tags(
            change,
            inst.changes_dir,
            repos=tuple(inst.repos),
            projects=declared_projects(inst.repos),
            splits=declared_split_names(inst.repos, inst.config),
        )
        if change.lower() in cycles:
            errors.append(cycles[change.lower()])
        path = tasks_path(change, inst.changes_dir)
        for warning in _tag_warnings(inst, path) if path.is_file() else []:
            print(warning)
        for error in errors:
            print(error)
        if errors:
            print(f"{len(errors)} problem(s) in {change}")
            failed += 1
            continue
        print(f"{change}: {len(groups)} task group(s), all tagged")
        promotions = group_promotions(groups)
        for group in groups:
            if group.number in promotions:
                to, by = promotions[group.number]
                urgency = f" (priority {group.priority}, promoted to {to} by group {by})"
            elif group.priority != Priority.NORMAL:
                urgency = f" (priority {group.priority})"
            else:
                urgency = ""
            print(f"  {group.number}. [{group.tag}] [{group.tier}] {group.title}{urgency}")
    return 1 if failed else 0


def cmd_check(args: argparse.Namespace, inst: Installation) -> int:
    """`openspec validate --all --strict --json` on the planning repo."""
    from agent_build_kit import openspec

    ok, output = openspec.check(inst.root)
    print(output, end="")
    for tasks in inst.tasks_files():
        for warning in _tag_warnings(inst, tasks):
            print(warning)
    problems = _needs_cycle_problems(inst)
    for message in problems.values():
        print(message)
    return 0 if ok and not problems else 1


def cmd_archive(args: argparse.Namespace, inst: Installation) -> int:
    from agent_build_kit import openspec

    print(openspec.archive(args.change, cwd=inst.root), end="")
    remove_change_logs(run_log_dir(inst.state_dir), args.change)
    remove_change_logs(e2e_output_dir(inst.state_dir), args.change)
    remove_change_transcripts(transcript_dir(inst.state_dir), args.change)
    return 0


def cmd_openspec(args: argparse.Namespace, inst: Installation) -> int:
    """Pass a command through to the OpenSpec CLI, in the planning repo."""
    from agent_build_kit import openspec

    result = subprocess.run([*openspec.command(), *args.args], cwd=inst.root, check=False)
    return result.returncode


def cmd_requeue(args: argparse.Namespace, inst: Installation) -> int:
    """Give a failed or held unit, or one parked on a held e2e-test split, another go.

    A unit parked on a held split is requeued with `--rework` (with a note saying what
    changed, or none) or `--restart`, which run the agent again and end the park; a plain
    requeue of it is refused while the split is held. A parked unit with a pull request or
    being built, and running, in-review and merged units, are refused as always.

    Three different things, and the command says which. By default the unit
    resumes where it stopped: a unit that failed its unit-test check because the
    toolchain was missing has its work on the branch, and redoing the agent's
    step would only spend the usage window to arrive at the same branch.
    `--rework` keeps the work and hands the agent the failure: a unit that
    failed unit-test on real errors (a type check, a lint rule, a test) saved the
    output, but a resume at `verify` runs the check again and meets the same
    errors, without the agent ever seeing them. `--restart` throws the attempt
    away — the review rounds so far and the failure it was handed — for a
    failure that was the attempt's own, such as a build on the wrong base,
    where resuming would judge work that was never valid.

    Editing the store by hand gets this wrong: a unit's place in its build is
    in its thread, so putting it back to `planned` and nothing else leaves the
    thread where the failure stopped it.
    """
    mode = "rework" if args.rework else "restart" if args.restart else "resume"

    def say(text: str, *, error: bool = False) -> None:
        print(text, file=sys.stderr if error else sys.stdout)

    # Absent from a namespace built by hand, as older callers do.
    note = getattr(args, "note", None) or ""
    if path := getattr(args, "note_file", None):
        note = Path(path).read_text()
    return requeue(inst, args.unit, mode, say=say, note=note, by=REQUEUE_BY)


def cmd_replan(args: argparse.Namespace, inst: Installation) -> int:
    """Plan the named, `--all` or `--failed` changes again, now.

    What a tick does for a change, whatever its recorded plan says: the plan is
    asked for and the `Needs:` lines linked, so the units stored are what the
    next tick would have produced. Started work is left as it is (the store
    keeps it), and only what differs from before is printed.
    """
    store = store_for(inst)
    on_disk = (
        sorted(
            path.name
            for path in inst.changes_dir.iterdir()
            if path.is_dir() and path.name != "archive"
        )
        if inst.changes_dir.is_dir()
        else []
    )
    records = planned_hashes(inst)
    max_attempts = inst.max_plan_attempts
    standing = {unit.change for unit in store.all()}

    if not (args.changes or args.all or args.failed or args.stale):
        for change in (path.parent.name for path in inst.tasks_files()):
            shown = _plan_state(records.get(change), max_attempts, change in standing)
            print(f"{change}: {shown}")
        print(
            "usage: abk replan CHANGE|UNIT... | --all | --failed | --stale [--limit N] [--forget] "
            "[--report] [--dry-run] [--accept-unplanned]"
        )
        return 2

    if args.dry_run and args.forget:
        print("abk replan: --dry-run and --forget cannot be used together")
        return 2
    if args.limit is not None and args.limit < 1:
        print("abk replan: --limit must be at least 1")
        return 2

    selected: dict[str, None] = {}
    refused = 0
    verb = "reporting" if args.report else "previewing" if args.dry_run else "planning"
    units = {unit.id: unit for unit in store.all()}
    for name in args.changes:
        change = name
        if name not in on_disk and name in units:
            change = units[name].change
            print(f"{name} is in change {change}: {verb} {change}")
        elif name not in on_disk and name.split("/")[0] in on_disk and "/" in name:
            change = name.split("/")[0]
            print(f"{name} is in change {change}: {verb} {change}")
        selected[change] = None
    if args.all:
        selected.update(dict.fromkeys(path.parent.name for path in inst.tasks_files()))
    if args.failed:
        selected.update(
            dict.fromkeys(
                path.parent.name
                for path in inst.tasks_files()
                if records.get(path.parent.name, {}).get("ok") is False
            )
        )

    if args.stale:
        now = spans.clock.now()
        for path in inst.tasks_files():
            change = path.parent.name
            record = records.get(change)
            if not record or not plan_is_stale(record):
                continue
            # A change a name, `--all` or `--failed` selected is planned, whatever it waits for.
            if (
                change not in selected
                and not record.get("ok")
                and _plan_rests(record, plan_digest(path, record.get("hash")), max_attempts, now)
            ):
                shown = _plan_state(record, max_attempts, change in standing)
                print(f"{change}: skipped — {shown}")
                continue
            selected[change] = None

    to_plan: list[str] = []
    for change in selected:
        tasks = inst.changes_dir / change / "tasks.md"
        if change not in on_disk:
            print(
                f"abk replan: {change!r} is not a change (changes: {', '.join(on_disk) or 'none'})"
            )
        elif not tasks.is_file():
            print(f"abk replan: {change} has no tasks.md")
        elif not args.forget and _validated(inst, tasks)[1]:
            print(f"abk replan: {change} has task-group problems — run `abk tags`")
        else:
            to_plan.append(change)
            continue
        refused += 1

    if args.stale or args.limit is not None:
        to_plan.sort(key=lambda change: (_urgency(inst, change), change))
    if args.limit is not None:
        for change in to_plan[args.limit :]:
            print(f"{change}: not yet planned (over --limit {args.limit})")
        to_plan = to_plan[: args.limit]

    if args.report:
        _print_replan_report(inst, store, to_plan)
        return 1 if refused else 0
    if args.dry_run:
        return _print_replan_dry_run(inst, store, to_plan, refused)
    if args.forget:
        record_plans(inst, dict.fromkeys(to_plan))
        for change in to_plan:
            print(f"forgot the plan of {change}; the next tick plans it")
        return 1 if refused else 0
    if not to_plan:
        print("no change to plan")
        return 1 if refused else 0

    ends_on_outage = args.stale or args.limit is not None
    # A run that stops at an outage names each change once, as it is planned or not tried.
    planning = f"{len(to_plan)} change(s)" if ends_on_outage else ", ".join(to_plan)
    print(f"planning {planning}: {len(to_plan)} model call(s)")
    failed: list[str] = []
    cyclic = False
    for index, change in enumerate(to_plan):
        with plan_apart(inst, store, [change]) as outcome:
            drops = _dropped(outcome)
            held = bool(drops) and not args.accept_unplanned
            if held:
                failed.append(change)
                for line in _held_back_lines(change, drops):
                    print(line)
            else:
                if not apply_planned(inst, store, outcome):
                    failed.append(change)
                    print(
                        f"{change}: the store changed while it was planned; nothing applied — "
                        f"run `abk replan {change}` again"
                    )
                    continue
                for line in _replan_lines(outcome):
                    print(line)
                if outcome.results[change].status != "planned":
                    failed.append(change)
                # Each refusal was printed above as the plan or the linking logged it.
                cyclic = cyclic or _cyclic(outcome)
            met_outage = outcome.results[change].status == "waiting"
        if ends_on_outage and met_outage:
            # The rest would meet the same outage.
            for rest in to_plan[index + 1 :]:
                print(f"{rest}: not tried — {change} met an outage")
            break
    release_split_changed(inst, store, only=set(to_plan))
    return 1 if refused or failed or cyclic else 0


def _urgency(inst: Installation, change: str) -> int:
    """The most urgent priority among a change's task groups; normal when none is readable."""
    groups, _ = _validated(inst, inst.changes_dir / change / "tasks.md")
    return min((group.priority for group in groups), default=Priority.NORMAL)


def _dropped(outcome: ReplanOutcome) -> list[StoredUnit]:
    """The units of the planned changes that `outcome` leaves `unplanned` and were not before,
    as they stood before. A unit the planning removed by joining it onto another is not one:
    its work went there."""
    return [
        old
        for uid, old in outcome.before.items()
        if old.change in outcome.changes
        and old.state != UNPLANNED
        and (after := outcome.after.get(uid)) is not None
        and after.state == UNPLANNED
    ]


def _held_back_lines(change: str, dropped: list[StoredUnit]) -> list[str]:
    """What a replan prints for a change whose plan it did not apply because it drops units."""
    lines = [f"{change}: the plan would leave {len(dropped)} unit(s) unplanned; nothing applied"]
    for unit in dropped:
        groups = ", ".join(str(n) for n in unit.groups)
        lines.append(f"  {unit.id}: {unit.state.value}, group(s) {groups}")
    lines.append("  run again with --accept-unplanned to store the plan")
    return lines


def _print_replan_dry_run(
    inst: Installation, store: UnitStore, changes: list[str], refused: int
) -> int:
    """What `abk replan` would store for `changes`, printed as a replan prints its result;
    nothing stored is written."""
    if not changes:
        print("no change to plan")
        return 1 if refused else 0
    print(f"dry run for {', '.join(changes)}: {len(changes)} planner call(s)")
    with plan_apart(inst, store, changes) as outcome:
        for line in _replan_lines(outcome, dry=True):
            print(line)
    print("nothing was stored: the log lines above count no attempt and no wait")
    failed = any(outcome.results[change].status != "planned" for change in changes)
    return 1 if refused or failed or _cyclic(outcome) else 0


class ReplanOutcome(Frozen):
    """What planning some changes produced: the planner's results, the units before and after,
    and the plan records of the changes. `scratch` is the directory of copies it was planned
    in, when it was planned apart (`plan_apart`)."""

    changes: tuple[str, ...]
    results: dict[str, PlanResult]
    refusals: tuple[CycleEdge, ...]
    before: dict[str, StoredUnit]
    after: dict[str, StoredUnit]
    records: dict[str, dict]
    # The units as the stored file had them when copied, before dependencies were reduced.
    base: dict[str, StoredUnit] = {}
    # Other changes whose plan records the planning removed, their groups being carried again.
    orphaned: tuple[str, ...] = ()
    scratch: Path | None = None


def _plan_changes(inst: Installation, store: UnitStore, changes: Sequence[str]) -> ReplanOutcome:
    """Ask for the plan of each of `changes` as a replan does, link the `Needs:` lines and
    promote, in `store` and `inst`'s plan records."""
    base = {unit.id: unit for unit in store.all()}
    reduce_stored_dependencies(store)
    before = {unit.id: unit for unit in store.all()}
    recorded = set(planned_hashes(inst))
    results = plan_all(inst, store=store, only=set(changes), force=True)
    refusals = link_needs(inst, store=store)
    _promote(inst, store)
    records = planned_hashes(inst)
    return ReplanOutcome(
        changes=tuple(changes),
        results=results,
        refusals=tuple(refusals),
        before=before,
        base=base,
        after={unit.id: unit for unit in store.all()},
        records={change: records.get(change, {}) for change in changes},
        orphaned=tuple(sorted(recorded - set(records) - set(changes))),
    )


@contextmanager
def plan_apart(
    inst: Installation, store: UnitStore, changes: Sequence[str]
) -> Iterator[ReplanOutcome]:
    """Plan `changes` against copies of the unit store, the plan records and the branch locks
    in a temporary directory, which lives as long as the block: nothing stored is written.

    The planner is asked once; `apply_planned` stores the outcome without asking again.
    """
    with tempfile.TemporaryDirectory(prefix="abk-plan-apart-") as tmp:
        scratch = Path(tmp)
        for source in (store.path, inst.state_dir / "planned.json"):
            if source.is_file():
                shutil.copy2(source, scratch / source.name)
        # The holds a split is under, which a unit's priority is promoted around.
        if (holds := held_path(inst.state_dir)).is_file():
            shutil.copy2(holds, scratch / holds.name)
        # A branch a live process holds is a unit that has started: a join onto it is dropped.
        if (inst.state_dir / "locks").is_dir():
            shutil.copytree(inst.state_dir / "locks", scratch / "locks")
        planning = inst.config.planning.model_copy(
            update={
                "state_dir": str(scratch),
                "graph_page": str(scratch / "graph.html"),
                "usage_page": str(scratch / "usage.html"),
            }
        )
        copy = Installation(inst.config.model_copy(update={"planning": planning}), inst.root)
        trial = UnitStore(scratch / store.path.name)
        yield _plan_changes(copy, trial, changes).model_copy(update={"scratch": scratch})


def apply_planned(inst: Installation, store: UnitStore, outcome: ReplanOutcome) -> bool:
    """Store a planned-apart `outcome`, inside its `plan_apart` block, and say whether it was
    stored. Only what the planning changed is written: the units that differ and the plan
    records of the planned changes and of those it orphaned, both under the store lock and
    the records' own, so neither is seen without the other. A network pause the planning
    recorded is recorded in the real state directory. A tick may have run while the planner
    was asked; when one of the units to write is no longer as the copy had it, nothing is
    written. The planner is not asked."""
    if outcome.scratch is None:
        raise ValueError("the outcome was not planned apart")
    # The outage was met in the copy, whose state directory goes with it: the pause is the
    # real one's to stand, and `record_pause` keeps one that already does.
    if pause := network_pause(outcome.scratch):
        record_pause(pause, marker=network_marker(inst.state_dir))

    def record_plan_records() -> None:
        update_plans(
            inst,
            lambda _: {
                **dict.fromkeys(outcome.orphaned),
                **{change: outcome.records[change] or None for change in outcome.changes},
            },
        )

    return not store.replace_if_unchanged(outcome.base, outcome.after, also=record_plan_records)


def _cyclic(outcome: ReplanOutcome) -> bool:
    """Whether a refusal runs in a cycle through a change planned here: another change's is
    left to the tick that links it, and does not fail this replan."""
    return any(
        outcome.after[unit_id].change in outcome.changes
        for edge in outcome.refusals
        for unit_id in edge.cycle
        if unit_id in outcome.after
    ) or any(outcome.results[change].cycle for change in outcome.changes)


def _replan_lines(outcome: ReplanOutcome, *, dry: bool = False) -> list[str]:
    """What a replan reports of `outcome` (`dry`: would report), a line each: a change taken
    without the planner, one that waits or failed (with the units the planner returned and
    why), joins dropped, each difference in the units with the joins, and the units kept."""
    lines: list[str] = []
    changes, results = outcome.changes, outcome.results
    for change in changes:
        if results[change].recorded_only:
            recorded = "would be recorded" if dry else "is recorded"
            lines.append(
                f"{change}: nothing was asked of the planner; {ALL_TAKEN}; the plan {recorded}"
            )
    for change in changes:
        if results[change].status == "planned":
            continue
        record = outcome.records[change]
        if results[change].status == "waiting":
            lines.append(
                f"{change}: {'would wait' if dry else 'waiting'} for "
                f"{PLAN_WAITS[record['waiting']]} — no attempt used; "
                f"next try {_shown_time(record.get('until')) or 'later'}"
            )
            continue
        lines.append(
            f"{change}: the plan would fail or be refused — the old plan stands"
            if dry
            else f"{change}: the plan failed — the old plan stands; see above"
        )
        if record.get("reason"):
            lines.append(f"{change}: {record['reason']}")
        if record.get("units"):
            lines.append(f"{change}: the planner returned {', '.join(record['units'])}")
    for change in changes:
        if results[change].dropped_joins:
            lines.append(
                f"{change}: {results[change].dropped_joins} join(s) dropped, a unit started"
            )
    differences = [
        *_replan_differences(outcome.before, outcome.after, dry=dry),
        *_join_lines(outcome, dry=dry),
    ]
    lines.extend(differences or ["nothing would change" if dry else "nothing changed"])
    for change in changes:
        for unit_id in results[change].kept:
            lines.append(f"kept: {unit_id} has work; not in the plan")
            lines.append(f"  `abk retire {unit_id} --reason TEXT` ends it and releases its groups")
    for unit in outcome.after.values():
        if unit.change in changes and unit.state not in (PLANNED, *BUILDS_NOTHING):
            lines.append(f"kept: {unit.id}, {unit.state.value}")
    return lines


def _carried_groups(unit: StoredUnit, change: str) -> set[int]:
    """The numbers of `change`'s groups `unit` builds, its own or joined."""
    return {n for member in unit.members() if member.change == change for n in member.groups}


def _join_lines(outcome: ReplanOutcome, *, dry: bool) -> list[str]:
    """A line, under the change, for its groups that joined a unit of another change: the
    unit joined onto and its estimate before and after."""
    lines: list[str] = []
    for change in outcome.changes:
        for unit in outcome.after.values():
            old = outcome.before.get(unit.id)
            if old is None or unit.change == change:
                continue
            if gained := _carried_groups(unit, change) - _carried_groups(old, change):
                groups = ", ".join(str(n) for n in sorted(gained))
                lines.append(
                    f"{change}: group(s) {groups} {'would join' if dry else 'joined'} onto "
                    f"{unit.id}, {old.estimated_lines} lines before, {unit.estimated_lines} after"
                )
    return lines


def _print_replan_report(inst: Installation, store: UnitStore, changes: list[str]) -> None:
    """What `abk replan` would do for `changes`, with no model call and no write: each
    change's plan state, its started and unstarted units with their groups, and whether
    the planner would be called."""
    records = planned_hashes(inst)
    units = store.all()
    calls = 0
    for change in changes:
        state = _plan_state(
            records.get(change), inst.max_plan_attempts, any(u.change == change for u in units)
        )
        print(f"{change}: {state}")
        mine = [unit for unit in units if unit.change == change]
        started = [unit for unit in mine if unit.state in _STARTED]
        unstarted = [unit for unit in mine if unit.state == PLANNED]
        print(f"  {len(started)} started, {len(unstarted)} unstarted")
        for unit in (*started, *unstarted):
            groups = ", ".join(str(n) for n in unit.groups)
            print(f"  {unit.id}: group {groups} ({unit.state.value})")
        task_groups, errors = _validated(inst, inst.changes_dir / change / "tasks.md")
        decided = _without_planner(inst, store, change, task_groups, errors)
        if decided is None:
            calls += 1
            print("  would call the planner once")
        elif decided[0] == "all_taken":
            print(f"  would ask nothing of the planner; {decided[1]}")
        else:
            why = decided[1] if isinstance(decided[1], str) else "; ".join(decided[1])
            print(f"  would be refused, no planner call: {why}")
    print(f"total: {calls} planner call{'' if calls == 1 else 's'}")


def _plan_state(record: dict | None, max_attempts: int, has_units: bool = False) -> str:
    """How a change's recorded plan reads in the listing `abk replan` gives."""
    if not record:
        return "never planned"
    if record.get("ok"):
        return (
            f"planned, stale: {plan_stale_reason(record)}" if plan_is_stale(record) else "planned"
        )
    attempts = record.get("attempts", 0)
    if record.get("waiting") in PLAN_WAITS:
        stale = (
            f", stale: {plan_stale_reason(record)}"
            if _plan_stands(record, has_units) and plan_is_stale(record)
            else ""
        )
        return (
            f"waiting for {PLAN_WAITS[record['waiting']]}{_since(record.get('since'))}"
            f"{_next_try(record.get('until'))} (attempts {attempts}/{max_attempts}, not used)"
            f"{stale}"
        )
    if attempts >= max_attempts:
        reason = f": {record['reason']}" if record.get("reason") else ""
        return f"given up{reason} — run `abk replan --failed`, or edit tasks.md"
    state = f"failing {attempts}/{max_attempts}"
    return f"{state}: {record['reason']}" if record.get("reason") else state


def _shown_time(moment: object) -> str | None:
    """A recorded time as a person reads it: local, to the minute; None when it is
    missing or unreadable."""
    try:
        return f"{datetime.fromisoformat(str(moment)).astimezone():%H:%M}"
    except ValueError:
        return None


def _since(moment: object) -> str:
    return f" since {shown}" if (shown := _shown_time(moment)) else ""


def _next_try(moment: object) -> str:
    return f", next try {shown}" if (shown := _shown_time(moment)) else ""


def _replan_differences(
    before: Mapping[str, StoredUnit], after: Mapping[str, StoredUnit], *, dry: bool = False
) -> list[str]:
    """What a replan changed in the store, a line for each difference and none for
    a unit that is the same. A new or re-estimated unit shows its review tier and its
    estimate against the ceiling of that tier."""
    lines: list[str] = []
    for uid, unit in after.items():
        old = before.get(uid)
        review = unit.review_tier or "full"
        sized = f"{unit.estimated_lines} of {unit_ceiling(unit)} lines"
        if old is None:
            groups = ", ".join(str(n) for n in unit.groups)
            lines.append(
                f"{uid}: {'would be stored' if dry else 'planned'}, groups {groups}, {sized}, "
                f"{review}, {unit.tier}"
            )
            continue
        if unit.state == UNPLANNED and old.state != UNPLANNED:
            reason = (
                f"replaced by {', '.join(unit.superseded_by)}"
                if unit.superseded_by
                else "the plan no longer has it"
            )
            lines.append(f"{uid}: {'would become' if dry else 'now'} unplanned, {reason}")
        if removed := [x for x in old.depends_on if x not in unit.depends_on]:
            lines.append(f"{uid}: no longer depends on {', '.join(removed)}")
        if added := [x for x in unit.depends_on if x not in old.depends_on]:
            lines.append(f"{uid}: now depends on {', '.join(added)}")
        if unit.estimated_lines != old.estimated_lines:
            lines.append(
                f"{uid}: estimate {old.estimated_lines} -> {unit.estimated_lines} lines "
                f"({sized}, {review})"
            )
        if unit.groups != old.groups:
            lines.append(
                f"{uid}: groups {', '.join(str(n) for n in old.groups)} -> "
                f"{', '.join(str(n) for n in unit.groups)}"
            )
        if unit.tier != old.tier:
            lines.append(f"{uid}: tier {old.tier} -> {unit.tier}")
        if unit.review_tier != old.review_tier:
            lines.append(f"{uid}: review tier {old.review_tier or 'full'} -> {review}")
    return lines


def _approval(inst: Installation, unit: StoredUnit) -> str | tuple[int, str]:
    """Why `unit` cannot be approved as stored, or the round and head to approve."""
    from agent_build_kit.serve.review import ReviewStore, branch_tip
    from agent_build_kit.serve.server import review_round

    if unit.pr is None:
        return f"{unit.id} has no pull request; nothing to approve"
    repo = inst.checkouts.get(unit.repo)
    head = branch_tip(repo, unit.branch) if repo is not None and repo.exists() else None
    if head is None:
        return f"{unit.id}'s pull request has no head: its branch is not in the checkout"
    round_ = review_round(inst, unit.id) or 1
    if any(
        d.round == round_ for d in ReviewStore(inst.state_dir / "reviews").read(unit.id).decisions
    ):
        return f"{unit.id}: round {round_} already has a decision"
    return round_, head


def approve_refusal(inst: Installation, unit: StoredUnit) -> str | None:
    """Why `unit` cannot be approved as stored; None when it can."""
    found = _approval(inst, unit)
    return found if isinstance(found, str) else None


def approve_unit(inst: Installation, unit_id: str, *, say: Callable[..., None]) -> int:
    """Record the person's approval of a unit's current review round at the head its
    pull request has; `abk approve` and the web UI both call this.

    Nothing is merged, pushed or voted on the host. Every message goes to `say`; the
    result is the command's exit code.
    """
    from agent_build_kit.serve.review import ReviewStore

    known = {unit.id: unit for unit in store_for(inst).all()}
    unit = known.get(unit_id)
    if unit is None:
        say(f"abk approve: no unit {unit_id!r} (known: {', '.join(sorted(known)) or 'none'})")
        return 1
    found = _approval(inst, unit)
    if isinstance(found, str):
        say(found)
        return 1
    round_, head = found
    summary = "approved from the command line or the web UI"
    verdict = ReviewStore(inst.state_dir / "reviews").decide(
        unit.id, round=round_, decision="approve", summary=summary, head=head
    )
    if verdict is None:
        say(f"{unit.id}: round {round_} already has a decision")
        return 1
    say(f"approved {unit.id} at {head} for round {round_}")
    return 0


def cmd_approve(args: argparse.Namespace, inst: Installation) -> int:
    """Record your approval of a unit's pull request in the review store.

    It is the same record the web UI's approve makes: the unit's current review
    round, at the head the pull request has now. It merges nothing, pushes nothing
    and casts no vote on the host.
    """
    return approve_unit(inst, args.unit, say=print)


def requeue_refusal(unit: StoredUnit) -> str | None:
    """Why `unit` cannot be requeued as stored; None when it can."""
    if unit.state in (FAILED, HELD):
        return None
    if unit.state == PLANNED and parked_on_split(unit):
        if unit.pr is not None:
            return (
                f"{unit.id} is parked on a split and has pull request #{unit.pr}; "
                "requeueing it would orphan the pull request"
            )
        return None
    return (
        f"{unit.id} is {unit.state}; only a failed or held unit can be requeued "
        "(a running one would be built twice, an in-review one has a PR to orphan)"
    )


def requeue(
    inst: Installation,
    unit_id: str,
    mode: str,
    *,
    say: Callable[..., None],
    note: str = "",
    because: str = "",
    by: str = "",
) -> int:
    """Give a failed or held unit another go; `abk requeue` and the web UI both call this.

    `mode` is `resume`, `rework` or `restart`, as `cmd_requeue` describes them. Every
    message goes to `say(text, error=...)` instead of being printed, so the caller
    decides where it shows. `by` is `REQUEUE_BY` when a person asked, which ends the unit's
    run of bounces; the pipeline's own requeues leave it empty. The result is the command's exit
    code.

    `note` is a person's instruction for the agent's next run; only `rework` and
    `restart` run the agent, so a plain requeue with one is refused. `because` is the
    history entry of a requeue the pipeline makes itself, in place of the default.
    """
    store = store_for(inst)
    known = {unit.id: unit for unit in store.all()}
    if unit_id not in known:
        say(
            f"abk requeue: no unit {unit_id!r} (known: {', '.join(sorted(known)) or 'none'})",
            error=True,
        )
        return 2
    if (refusal := requeue_refusal(known[unit_id])) is not None:
        say(refusal)
        return 1
    if note and mode == "resume":
        say(
            f"{unit_id}: a note is read by the agent, and a plain requeue resumes a step "
            "without running it; use --rework or --restart with --note"
        )
        return 1
    parked = known[unit_id].state == PLANNED and parked_on_split(known[unit_id])
    if parked and mode == "resume" and (refusal := _parked_resume_refusal(inst, known[unit_id])):
        say(refusal)
        return 1
    # A rework or restart of a parked unit ends its park, once the delivery has been made.
    clears_park = parked and mode != "resume"
    names = ", ".join(known[unit_id].parked_splits)
    # What the history says of a requeue of a parked unit: the splits and the person's note.
    parked_said = guidance_excerpt(note) if clears_park else ""
    if clears_park and not because:
        because = ("reworking" if mode == "rework" else "starting over") + f", parked on {names}"
    automatic = clears_park and mode == "rework" and not note
    if automatic:
        note = (
            f"Automatic note: this unit was parked on e2e-test split {names} and the person "
            "asked for the agent to run again. Read the group's tasks in tasks.md and the "
            "failing or mis-tagged tests, and apply them."
        )
    why = {
        "rework": RequeueReason.FROM_FAILURE,
        "restart": RequeueReason.RESTART,
        "resume": RequeueReason.RESUME,
    }[mode]
    if mode == "rework" and not known[unit_id].feedback and not note and not parked:
        say(
            f"{unit_id} has no saved failure to rework from; "
            "--restart starts it over, a plain requeue resumes it"
        )
        return 1
    if (
        by == REQUEUE_BY
        and known[unit_id].state == HELD
        and known[unit_id].held_by == HeldBy.REVIEW
        and known[unit_id].cause is Cause.TOO_BIG_FOR_TIER
    ):
        # A person who reads an oversized unit and lets it through is not held by the same rule.
        store.set_size_waived(unit_id)
    waits = waiting_on(known[unit_id], list(known.values()))
    merging = merge_parents(known[unit_id], waits, list(known.values()), config.active().repos)
    # What the history entry of a requeue says of a note: its first 200 characters.
    said = guidance_excerpt(note) if not clears_park else ""
    # With no saved failure the person's note is what the rework is from.
    saved = bool(known[unit_id].feedback)
    source = (
        "the saved failure"
        if saved
        else "an automatic note naming the splits it was parked on"
        if automatic
        else "the person's note"
    )
    if waits and has_thread(inst, unit_id):
        # A dependency is unmet: the thread is left where it stopped, and the pass
        # delivers the event in this mode once nothing the unit waits on is left (a
        # same-repo parent in review, a cross-repo parent merged).
        store.set_state(
            unit_id,
            PLANNED,
            note=(
                f"requeued: {dependency_wait(waits, merging=merging)}"
                + (f", parked on {names}{parked_said}" if clears_park else said)
            ),
            cause=Cause.GATED,
            by=by,
        )
        if note:
            store.set_guidance(unit_id, note)
        store.set_gated_requeue(unit_id, why)
        wait = dependency_wait(waits, merging=merging)
        say(f"{unit_id} requeued ({mode}), {wait}")
        return _requeued(store, unit_id, clears_park)
    try:
        delivered = resume_thread(
            inst,
            known[unit_id],
            "requeue",
            store=store,
            reason=because or mode,
            requeue=why,
            guidance=note,
        )
    except BranchBusy as error:
        say(f"{unit_id} is being built ({error}); requeue it again once it has stopped")
        return 1
    if delivered:
        outcome = delivered.outcome
        say(
            f"{unit_id} thread resumed ({mode}): {outcome.status} — {outcome.detail}",
            error=delivered.raised,
        )
        return 1 if delivered.raised else _requeued(store, unit_id, clears_park)
    if note and mode != "restart":
        store.set_guidance(unit_id, note)
    if mode == "rework":
        store.set_state(
            unit_id,
            PLANNED,
            note=(
                f"requeue: {because}{parked_said}"
                if because
                else f"requeued: reworking from {source}{said}"
            ),
            cause=Cause.REQUEUED,
            by=by,
        )
        say(
            f"{unit_id} requeued, the agent will rework it from "
            + ("the failure it saved" if saved else source)
        )
    elif mode == "restart":
        store.set_feedback(unit_id, "")
        if note:
            store.set_guidance(unit_id, note)
        store.set_state(
            unit_id,
            PLANNED,
            note=f"requeued: starting over{said}"
            if not clears_park
            else f"requeue: {because}{parked_said}",
            cause=Cause.REQUEUED,
            by=by,
        )
        say(f"{unit_id} requeued, starting over from the agent's step")
    else:
        store.set_state(
            unit_id,
            PLANNED,
            note=f"requeue: {because}" if because else "requeued: resuming where it stopped",
            cause=Cause.REQUEUED,
            by=by,
        )
        say(f"{unit_id} requeued, resuming where it stopped")
    return _requeued(store, unit_id, clears_park)


def _parked_resume_refusal(inst: Installation, unit: StoredUnit) -> str | None:
    """Why a plain requeue of a unit parked on a split would resume onto the wrong thing:
    a split it is parked on is held, or its group moved to another split. None otherwise."""
    if held := parked_holds(inst.config, inst.state_dir, unit):
        return (
            f"{unit.id} is parked on e2e-test split {', '.join(unit.parked_splits)} "
            f"(held: {'; '.join(hold.reason for hold in held.values())}); "
            "give --rework with a note saying what changed, or release the split"
        )
    if split_changes(inst, [unit]):
        return (
            f"{unit.id}'s group moved to another split; the pass reworks it, "
            "and resuming would run the old tests (--rework asks for it now)"
        )
    return None


def _requeued(store: UnitStore, unit_id: str, clears_park: bool = False) -> int:
    """The exit code of a requeue that took effect; the line a closed prerequisite left in
    the status goes with it, and stays for a requeue that was refused. `clears_park` ends the
    unit's park on a split, which a delivery has made unnecessary."""
    if clears_park:
        store.set_parked(unit_id)
    if store.get(unit_id).wait_ended:
        store.set_wait_ended(unit_id, "")
    return 0


def unit_groups(inst: Installation | None, repo: Path) -> tuple[GroupStep, ...]:
    """The groups of the unit named by the `Unit:` trailer of the checked-out branch's tip,
    as the build reads them; none outside an installation, with no trailer or for an
    unknown unit."""
    if inst is None:
        return ()
    trailer = git(repo, "log", "-1", "--format=%(trailers:key=Unit,valueonly)", check=False)
    unit_id = trailer.stdout.strip()
    store = UnitStore(inst.state_dir / "units.json")
    known = {stored.id: stored for stored in store.all()}
    if unit_id not in known:
        return ()
    return group_steps_of(inst.root, known[unit_id])


def cmd_gate(args: argparse.Namespace, inst: Installation | None) -> int:
    """The push gate, for a branch in a checkout: tests-first order, clean
    and red at the tests commit."""
    from agent_build_kit import profiles
    from agent_build_kit.config import BuildersConfig
    from agent_build_kit.pipeline.check_runner import CheckCache
    from agent_build_kit.pipeline.gate import check_branch
    from agent_build_kit.profiles.base import stubbed_build

    profile_name = args.profile
    base = args.base
    projects = []
    builders = BuildersConfig()
    if inst is not None:
        builders = inst.config.builders
        repo = Path(args.repo).resolve()
        for name, path in inst.checkouts.items():
            if repo == path.resolve() or repo.is_relative_to(path.resolve()):
                profile_name = profile_name or inst.repo(name).profile
                projects = inst.repo(name).projects
                # The remote's copy, as the runner builds on: the local branch of
                # that name is the user's, and nothing updates it.
                base = base or local_ref(trunk_of(name), repo=name)
                break
    profile = profiles.get(profile_name or "python-uv")
    cache = CheckCache(args.cache) if args.cache else None
    stubbed = stubbed_build(builders, profile)
    problems = check_branch(
        Path(args.repo),
        base or "main",
        cache=cache,
        profile=profile,
        projects=projects,
        stubbed=stubbed,
        groups=unit_groups(inst, Path(args.repo)) if stubbed else (),
    )
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
    status.add_argument(
        "--refresh",
        action="store_true",
        help="ask the usage endpoint for a fresh reading, within the minimum interval",
    )
    status.set_defaults(func=cmd_status)

    graph = sub.add_parser("graph", help="regenerate the unit graph page")
    graph.set_defaults(func=cmd_graph)

    verify = sub.add_parser(
        "verify", help="deploy a merged change and run its live tests, then archive it"
    )
    verify.add_argument("change")
    verify.set_defaults(func=cmd_verify)

    tags_help = "validate a change's task-group tags (name a change, or --all for every change)"
    tags = sub.add_parser("tags", help=tags_help, description=tags_help)
    tags.add_argument("change", nargs="?", help="the change to check")
    tags.add_argument("--all", action="store_true", help="every change in the store")
    tags.add_argument(
        "--fix", action="store_true", help="rewrite the old test-kind tags of open changes"
    )
    tags.add_argument(
        "--dry-run", action="store_true", help="with --fix, print what would be rewritten"
    )
    tags.set_defaults(func=cmd_tags)

    check = sub.add_parser("check", help="openspec validate --all --strict --json")
    check.set_defaults(func=cmd_check)

    requeue = sub.add_parser(
        "requeue",
        help="give a failed or held unit, or one parked on a held e2e-test split, another go",
    )
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
        "(a failed check), instead of resuming into the same failure; accepts a unit "
        "parked on a held e2e-test split, with or without a note",
    )
    given = requeue.add_mutually_exclusive_group()
    given.add_argument(
        "--note",
        metavar="TEXT",
        help="a person's instruction for the agent's next run, shown ahead of any saved failure; "
        "needs --rework or --restart (a unit parked on a held split is accepted by both)",
    )
    given.add_argument("--note-file", metavar="PATH", help="--note, read from a file")
    requeue.set_defaults(func=cmd_requeue)

    retire = sub.add_parser(
        "retire", help="end a unit that has not finished and release its groups"
    )
    retire.add_argument("unit", help="the unit id, e.g. add-marker/1")
    retire.add_argument(
        "--reason",
        metavar="TEXT",
        default="",
        help="why; needed when a group no unit builds is released",
    )
    retire.add_argument(
        "--delete-branch",
        action="store_true",
        help="also remove the worktree and delete the local and remote branch",
    )
    retire.add_argument(
        "--discard-unpushed",
        action="store_true",
        help="with --delete-branch, accept losing commits that were never pushed",
    )
    retire.add_argument(
        "--dry-run", action="store_true", help="print every step and change nothing"
    )
    retire.set_defaults(func=cmd_retire)

    replan = sub.add_parser("replan", help="plan changes again now, whatever their recorded plan")
    replan.add_argument("changes", nargs="*", help="change names, or unit ids")
    replan.add_argument("--all", action="store_true", help="every active change")
    replan.add_argument(
        "--failed", action="store_true", help="every change whose last plan failed or gave up"
    )
    replan.add_argument(
        "--stale", action="store_true", help="every change whose plan is stale and may be tried"
    )
    replan.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="plan only the first N selected changes, the most urgent first",
    )
    replan.add_argument(
        "--forget", action="store_true", help="only clear the recorded plans; make no model call"
    )
    replan.add_argument(
        "--report",
        action="store_true",
        help="only show what a replan would do for each change; no model call, no write",
    )
    replan.add_argument(
        "--accept-unplanned",
        action="store_true",
        help="store a plan that leaves units of a change unplanned; without it nothing is applied",
    )
    replan.add_argument(
        "--dry-run",
        action="store_true",
        help="ask the planner and show the units each change would get; write nothing",
    )
    replan.set_defaults(func=cmd_replan)

    approve = sub.add_parser(
        "approve", help="record your approval of a unit's current review round"
    )
    approve.add_argument("unit", help="the unit id, e.g. add-marker/1")
    approve.set_defaults(func=cmd_approve)

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


# Told in the decision log with each record, so the records of one process read together.
_PROCESS_TICK = uuid.uuid4().hex[:8]


def wait_reasons(
    inst: Installation,
    units: list[StoredUnit],
    *,
    started: set[str],
    building: set[str],
    only: frozenset[str],
    idle: Collection[str] = (),
    usage_paused: bool = False,
) -> dict[str, Wait]:
    """The one reason each unit that is not running is not, with what it waits on.

    Decided from the facts `_evaluate_round` decides on, so what starts is unchanged:
    a unit it would start is `ready`, one it leaves out is told by what holds it."""
    ready, view, _excluded, for_the_lane, _emergency = _evaluate_round(
        inst,
        units,
        started=started,
        building=building,
        only=only,
        idle=idle,
    )
    return _waits_in(
        inst,
        units,
        view,
        startable={unit.id for unit in ready} | for_the_lane,
        skipped=_parked_starts(units, started) | building,
        only=only,
        usage_paused=usage_paused,
    )


def _waits_in(
    inst: Installation,
    units: list[StoredUnit],
    view: list[Unit],
    *,
    startable: set[str],
    skipped: set[str],
    only: frozenset[str],
    usage_paused: bool,
    refused: Mapping[str, str] | None = None,
) -> dict[str, Wait]:
    """The reasons of `wait_reasons` from an evaluation a pass has already made: a unit
    in `skipped` is running or started, and one in `startable` is ready."""
    leases = Leases(lease_dir(inst.state_dir))
    now = spans.clock.now()
    waits: dict[str, Wait] = {}
    gates = split_gates(inst.config, inst.state_dir, units)
    # By the stored state: the view shows what a pass leaves out as held.
    for unit in units:
        # What `--only` leaves out is not waiting for anything this pass decides.
        if unit.id in skipped or (only and unit.id not in only):
            continue
        if unit.state == IN_REVIEW:
            waits[unit.id] = Wait(reason=WaitReason.WAITING_REVIEW)
        elif unit.state == HELD and unit.held_by is HeldBy.DEPTH:
            # Clears by itself when a merge frees the depth: it waits on work, not a person.
            current = shown_dependencies(unit, view)
            parents = tuple(
                parent.id
                for parent in view
                if parent.id in current and parent.state not in (MERGED, CLOSED, SATISFIED)
            )
            waits[unit.id] = Wait(reason=WaitReason.BLOCKED, waits_on=parents)
        elif unit.state in (HELD, FAILED):
            waits[unit.id] = Wait(reason=WaitReason.NEEDS_PERSON)
        elif unit.state == PLANNED:
            waits[unit.id] = _planned_wait(
                inst,
                unit,
                view,
                leases,
                now,
                startable,
                gates,
                usage_paused=usage_paused,
                refusal=(refused or {}).get(unit.id),
            )
    return waits


def _planned_wait(
    inst: Installation,
    unit: StoredUnit,
    view: list[Unit],
    leases: Leases,
    now: datetime,
    startable: set[str],
    gates: Mapping[str, Hold],
    *,
    usage_paused: bool,
    refusal: str | None = None,
) -> Wait:
    if leases.holder(unit.id) is not None:
        return Wait(reason=WaitReason.LEASE)
    if backoff_remaining(unit, now) is not None:
        return Wait(reason=WaitReason.BACKOFF)
    if parents := shown_waits(unit, view):
        return Wait(reason=WaitReason.BLOCKED, waits_on=tuple(parent.id for parent in parents))
    if steps := unmet_steps(unit):
        return Wait(reason=WaitReason.MANUAL, detail=manual_status_line(steps[0]))
    if parked_for_manual_step(unit):
        # Its steps are done and the resume is yet to be delivered: not ready, whatever follows.
        return Wait(reason=WaitReason.MANUAL, detail="manual steps done, readmitting")
    # Not ready for want of work another unit has to finish: a requeue gated on a merge,
    # or a stack deeper than may be built until what it stacks on merges.
    if awaits_release(unit) or depth_of(unit, view) > inst.stack_depth_build_cap:
        return Wait(reason=WaitReason.BLOCKED)
    if (gate := gates.get(unit.id)) is not None:
        return Wait(
            reason=WaitReason.SPLIT,
            detail=f"waiting for e2e-test split {unit.split}: {hold_text(gate)}",
        )
    if refusal is not None:
        # Its own account refused it at admission: the wait says which account and why.
        return Wait(reason=WaitReason.USAGE_PAUSE, detail=refusal)
    if usage_paused:
        return Wait(reason=WaitReason.USAGE_PAUSE)
    if unit.id in startable:
        return Wait(reason=WaitReason.READY)
    slot_of = _slot_of(inst)
    room = start_room(view, _slot_limit(inst)(slot_of(unit)), slot_of(unit), slot_of)
    if not in_progress(unit, view) and not room:
        return Wait(reason=WaitReason.QUEUE_FULL)
    return Wait(reason=WaitReason.SLOT)


# One recorder for each decision log, so the log is read once when a process first
# records, not on every refresh.
_RECORDERS: dict[Path, WaitRecorder] = {}


# A unit waiting for these has nothing blocking it: it is ready, whatever holds its start.
_READY_REASONS = frozenset({WaitReason.READY, WaitReason.SLOT, WaitReason.USAGE_PAUSE})


def _parked_starts(units: Sequence[StoredUnit], started: Collection[str]) -> set[str]:
    """The units this pass started that are stored `planned` again: they wait for the next
    pass. One started that has since reached review, a hold or a failure is judged by its
    stored state, so its wait is dated from when it began."""
    return {unit.id for unit in units if unit.id in started and unit.state == PLANNED}


def _record_waits(
    inst: Installation,
    store: UnitStore,
    units: Sequence[StoredUnit],
    only: frozenset[str],
    waits: Callable[[], dict[str, Wait]],
) -> None:
    """Log each unit's reason for waiting where it changed; a pass is never failed by it.
    A unit `--only` leaves out is not looked at, so its wait is neither changed nor closed."""
    try:
        path = inst.state_dir / DECISIONS_NAME
        if path not in _RECORDERS:
            _RECORDERS[path] = WaitRecorder(path, log)
        left_out = [unit.id for unit in units if only and unit.id not in only]
        reasons = waits()
        _RECORDERS[path].record(reasons, tick=_PROCESS_TICK, keep=left_out)
        # Where reasons are decided, so a tick that starts nothing still dates a unit's readiness.
        unstamped = {unit.id for unit in units if unit.ready_at is None}
        for unit_id, wait in reasons.items():
            if unit_id in unstamped and wait.reason in _READY_REASONS:
                store.mark_ready(unit_id)
    except Exception as error:  # noqa: BLE001 — a record is never a pass's to lose
        log(f"the decision log is not recording ({type(error).__name__}: {error})")
