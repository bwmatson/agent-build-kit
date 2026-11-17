"""The worker's runs: building, resolving and verifying one unit."""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import (
    Callable,
    Sequence,
)
from contextlib import AbstractContextManager, ExitStack, nullcontext
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from agent_build_kit import (
    claude_account,
    config,
    orchestration,
    profiles,
    runtimes,
    telemetry,
)
from agent_build_kit.budget import cut_head
from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent, UnitRun
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.orchestration.artifacts import INTERFACE as ARTIFACTS
from agent_build_kit.pipeline import (
    code_host,
    demotion_triggers,
    diagram,
    landing_intent,
    loaded_code,
    network_probe,
    spans,
    usage_report,
)
from agent_build_kit.pipeline.demotion_record import DEMOTIONS
from agent_build_kit.pipeline.drafts import StateDrafts
from agent_build_kit.pipeline.e2e import (
    LOCK_WAIT_SETTING,
    stack_lock,
)
from agent_build_kit.pipeline.e2e_holds import (
    split_gates,
)
from agent_build_kit.pipeline.file_lock import (
    file_lock,
)
from agent_build_kit.pipeline.git_output import PUSH_OPERATION
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.metric_records import emit_metric
from agent_build_kit.pipeline.pause import (
    Pause,
    network_marker,
    pause_for,
    pause_in_force,
    pause_line,
    pause_marker,
    pause_until,
)
from agent_build_kit.pipeline.planning_repo import (
    repo_sharing,
)
from agent_build_kit.pipeline.pr_poller import (
    recorded_checks,
)
from agent_build_kit.pipeline.resolution_lane import (
    Lane,
    Rest,
    about_the_move,
    base_tip,
    forget_run_attempt,
    hold_if_spent,
    in_a_lane_run,
    lane_record,
    record_run_attempt,
)
from agent_build_kit.pipeline.restack import (
    ConflictSession,
    Moved,
    TemporaryTree,
    checked_out_at,
    push_with_lease,
    resolved_move,
)
from agent_build_kit.pipeline.run_log import (
    RunLog,
    run_ledger_path,
)
from agent_build_kit.pipeline.stack_runner import (
    PauseInfo,
    RunOutcome,
    RunStatus,
    UnitOutcome,
    UnitRunner,
)
from agent_build_kit.pipeline.ui_review import (
    ui_notes_of,
    unit_patch_of,
)
from agent_build_kit.pipeline.unit_store import (
    PARK_BACKOFF,
    PARKED_CAUSES,
    Cause,
    HeldBy,
    RequeueReason,
    ReworkKind,
    StoredUnit,
    UnitStore,
    feedback_source_of,
)
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    Unit,
    UnitState,
    base_of,
    branch_name,
    local_ref,
)
from agent_build_kit.pipeline.usage_forecast_ask import Ask
from agent_build_kit.pipeline.usage_guard import (
    Decision,
    Interrupted,
    RateLimited,
    ask_before_call,
    current_usage,
    decide_start,
    held_usage,
    may_start_unit,
    starting,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from agent_build_kit.pipeline.verify import SplitHeld, Verification, VerifyRecord, verify_change
from agent_build_kit.pipeline.wiring import (
    Run,
    build_on_flake,
    build_resume_at,
    build_runner,
    build_unit_test,
    build_usage_gate,
    moving_onto,
    own_work_starts_after,
)
from agent_build_kit.pipeline.work_graph import (
    TaskGroup,
    ValidationError,
    declared_profiles,
    declared_projects,
    declared_split_names,
    project_source_note,
    validate_tasks,
)
from agent_build_kit.pipeline.workspaces import (
    BranchBusy,
    branch_held,
    branch_lock,
    checked_out_elsewhere,
    unit_tree,
    worktree_key,
)
from agent_build_kit.profiles.base import ProfileUnsupported
from agent_build_kit.redaction import redact_text
from agent_build_kit.runtimes import AgentRateLimited, NetworkUnavailable, ServiceUnavailable
from agent_build_kit.runtimes.base import LoginRejected

if TYPE_CHECKING:
    from agent_build_kit.graph.unit import Position
    from agent_build_kit.pipeline.events import Restack


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(message: str, *, at: str | None = None) -> None:
    print(f"[{at or stamp()}] {redact_text(message, where='printed output')}", flush=True)


def project_source_notes(inst: Installation, units: Sequence[StoredUnit]) -> dict[str, str]:
    """For each unit whose project a group's resolution or `[repo/<root>]` set, by unit id, the
    note saying so (`project_source_note`): the source of the unit's first group. Empty when no
    repo declares a project, since nothing is then resolved."""
    if not any(declared_projects(inst.repos).values()):
        return {}
    catalog = _task_catalog(inst)
    notes: dict[str, str] = {}
    for unit in units:
        member = next((m for m in unit.members() if m.groups), None)
        if member is None:
            continue
        group = next(
            (g for g in catalog.get(member.change, ()) if g.number == member.groups[0]), None
        )
        if group and group.project == unit.project and (note := project_source_note(group)):
            notes[unit.id] = note
    return notes


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
                unit_notes=project_source_notes(inst, units),
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
        try:
            # Late: the tracker step belongs to the dispatcher's package.
            from agent_build_kit.trackers.tick_step import note_state_change

            note_state_change(inst, unit.repo)
        except Exception as error:  # noqa: BLE001
            log(f"tracker mirror not marked — {type(error).__name__}: {error}")
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


def _paused_marker(inst: Installation, account: claude_account.Account) -> Path:
    """The marker of `account`'s pause: the default account's is also the network's."""
    return pause_marker(inst.state_dir, account)


def _paused_for(inst: Installation, unit: StoredUnit | Unit) -> Pause | None:
    """The pause in force for the unit's own account: its marker's, or a network outage."""
    return pause_for(inst.state_dir, claude_account.for_repo(inst.config, unit.repo))


def _pause_report(inst: Installation, pause: Pause, *, verb: str = "paused") -> str:
    """`pause_line`, naming the account and kind of a pause when the installation keeps accounts
    apart. A network pause is the whole installation's, so it names none."""
    line = pause_line(pause, verb=verb)
    if pause.kind == "network" or not (
        pause.account or claude_account.slots_per_account(inst.config)
    ):
        return line
    return f"account {pause.account or 'default'} ({pause.kind}): {line}"


def _demote_failed_verify(inst: Installation, change: str, units: list) -> None:
    demotion_triggers.demote_for_failed_verify(
        change,
        units,
        verdicts=inst.state_dir / VERDICTS,
        demotions=inst.state_dir / DEMOTIONS,
        at=datetime.now(UTC),
        log=log,
    )


def restacking_bases(inst: Installation) -> dict[str, str]:
    """The base of each unit the restack lane of a live tick holds, running or waiting."""
    return {entry["unit"]: entry["base"] for entry in lane_record(inst.state_dir)}


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
    return _verify_locked(inst, change, units, wait=None, reuse_recorded=True)


def _verify_locked(
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
            if last is not None and last.units == _merged_ids(change, units):
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


def _merged_ids(change: str, units: list) -> list[str]:
    # The same rule `verify_change` records its units by: a merged unit with a PR.
    return sorted(u.id for u in units if u.carries(change) and u.state == MERGED and u.pr)


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
        log(f"verifying {change} skipped — the live stack is in use; tried again next round")
        return None
    except SplitHeld as held:
        log(f"verifying {change} skipped — {held}; tried again next round")
        return None
    except Exception as error:  # noqa: BLE001 — recorded, never silently skipped
        outcome = Verification(
            change=change,
            passed=False,
            detail=f"{type(error).__name__}: {error}",
            units=_merged_ids(change, units),
        )
    record = VerifyRecord(inst.state_dir / "verified.json")
    if record.get(change) == outcome:
        return outcome
    record.put(outcome)
    if outcome.passed:
        log(f"verified {change}: {', '.join(outcome.deployed) or 'nothing to deploy'}")
    else:
        log(f"NOT archiving {change} — verification failed:\n{outcome.detail}")
        _demote_failed_verify(inst, change, units)
    return outcome


def _decision_key(
    account: claude_account.Account, tier: ReviewTier | None, lines: int, *, plan_due: bool = False
) -> str:
    """Where `decided` keeps the decision for a start of this tier and size on `account`: units
    of one tier and size are asked of the guard once. A start that reserves the plan call is not
    the start a unit's gate asks for, so it is kept apart."""
    return f"{claude_account.account_key(account)}|{tier}|{lines}|{plan_due}"


def _account_decision(
    account: claude_account.Account,
    decided: dict[str | None, Decision] | None,
    ask: Ask | None = None,
    *,
    unit: StoredUnit | None = None,
) -> Decision:
    """The guard's decision for `account`, asked once for each account `decided` holds, for
    what the round asks (see `_round_ask`) when it names one. For a `unit` it is the decision
    the gate before the unit's first agent step takes, for the unit's own review tier and
    estimated lines. A unit's decision is kept under its id, since a refusal names the unit it
    was asked for; an allowance names none and is shared by units of that tier and size."""
    key = claude_account.account_key(account)
    named = ask or Ask()
    if unit is not None:
        named = Ask(
            unit=unit.id, tier=ReviewTier.parse(unit.review_tier), lines=unit.estimated_lines
        )
    sized = (
        _decision_key(account, named.tier, named.lines, plan_due=named.plan_due)
        if named.lines is not None and named.step is None
        else None
    )
    if decided is not None:
        kept = [unit.id, sized] if unit is not None and sized is not None else [key]
        for found in kept:
            if found in decided:
                return decided[found]
    # A unit's ask is made as the gate makes it: the unit is named, so its id is in the reason
    # and an allowance on an estimate is kept under it. The round's ask names no unit.
    scope = (
        starting(unit.id, review_tier=named.tier, estimated_lines=named.lines)
        if unit is not None
        else nullcontext()
    )
    with scope:
        decision = decide_start(
            read=current_usage,
            decide=may_start_unit,
            account=account,
            review_tier=named.tier,
            estimated_lines=named.lines,
            step=named.step,
            plan_due=named.plan_due,
        )
    if decided is not None:
        decided[key if unit is None else unit.id] = decision
        # Only an allowance not made on an estimate names no unit, so only it is shared.
        if sized is not None and decision.may_start and not decision.estimate:
            decided[sized] = decision
    return decision


def _start_decision(
    accounts: Sequence[claude_account.Account],
    decided: dict[str | None, Decision] | None = None,
    ask: Ask | None = None,
) -> Decision:
    """The guard's decision to start, under this module's names for reading and judging: a start
    on any of `accounts` is a start. When every one refuses, the
    refusal names each and waits for the earliest of their times. `decided` keeps each account's
    decision for the rest of the round, and `ask` is what it is forecast for."""
    refusals: list[Decision] = []
    for account in accounts:
        decision = _account_decision(account, decided, ask)
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


def gated_units(inst: Installation, units: Sequence[StoredUnit]) -> frozenset[str]:
    """The ids of the units a held e2e-test split keeps from starting."""
    return frozenset(split_gates(inst.config, inst.state_dir, units))


def _clear_starting(store: UnitStore, unit_id: str) -> None:
    """Drop the unit's `starting` marker: its worker has taken the branch's lock, which holds the
    place from then, or is done. A unit gone from the store has none."""
    try:
        if store.get(unit_id).starting is not None:
            store.set_starting(unit_id, None)
    except KeyError:
        pass


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
    return branch_held(branch, root=inst.locks_dir)


def thread_of(inst: Installation, unit_id: str) -> Position:
    """Where the unit's thread stands; its `state` is None when it has none."""
    # Late: the graph package imports the pipeline.
    from agent_build_kit.graph.unit import thread_position
    from agent_build_kit.orchestration.checkpoints import open_checkpoints

    async def look() -> Position:
        async with open_checkpoints(inst) as saver:
            return await thread_position(saver, unit_id)

    return asyncio.run(look())


def has_thread(inst: Installation, unit_id: str) -> bool:
    """Whether a thread exists for the unit."""
    return thread_of(inst, unit_id).state is not None


def _task_catalog(inst: Installation) -> dict[str, tuple[TaskGroup, ...]]:
    """Every change's task groups, as `unit_priority` and the plan check read them."""
    return {path.parent.name: tuple(_validated(inst, path)[0]) for path in inst.tasks_files()}


def repo_turn(installation: Installation, repo: str) -> AbstractContextManager[None]:
    """The turn a repo's `.git` is taken by. Adding a worktree, pushing, moving
    or removing a branch all take git's own locks there, which fail rather
    than wait."""
    return file_lock(installation.locks_dir / f"repo-{repo}.lock")


def build_repo_unit_test(
    installation: Installation,
    name: str,
    *,
    log: Callable[[str], None],
    run: Run | None = None,
) -> Callable[..., tuple[bool, str]]:
    """The unit-test as repo `name` builds it: its toolchain profile, root extras, projects and
    settings, and where failure bundles are kept. The one place that is assembled from a repo's
    configuration, for a unit's own checks, a moved-base run and the default-branch check of a
    late failure."""
    repo = installation.repo(name)
    make = partial(
        build_unit_test,
        profile=profiles.get(repo.profile),
        root_extras=repo.tests.root_extras,
        projects=repo.projects,
        repo=repo,
        log=log,
        failures_dir=orchestration.get(ARTIFACTS, installation),
        installation=installation,
        test_runs=run_ledger_path(installation.state_dir),
    )
    return make() if run is None else make(run=run)


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


def resolution_procedure(
    inst: Installation,
    store: UnitStore,
    *,
    moves: StackMoves,
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
            if branch_is_held(inst, store.get(unit_id).branch or branch_name(store.get(unit_id))):
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
            path,
            branch,
            name=names[path],
            turn=partial(repo_turn, installation, names[path]),
            **kwargs,
        )

    def unit_test_of(*, cwd: Path, base: str, moved_from: str | None = None) -> tuple[bool, str]:
        """Unit-test as the repo whose checkout, or worktree of it, `cwd` is builds it."""
        name = next((each for each, path in checkouts.items() if path == cwd), None)
        if name is None:
            # Two repos can share one repository: the folder a worktree is in says whose it is.
            name = next(
                (
                    each
                    for each, path in checkouts.items()
                    if worktree_key(each) == cwd.parent.name and repo_sharing({each: path}, cwd)
                ),
                None,
            ) or repo_sharing(checkouts, cwd)
        if name is not None:
            return build_repo_unit_test(installation, name, log=log)(
                cwd=cwd, base=base, moved_from=moved_from
            )
        raise ValueError(f"{cwd} is not a checkout of any repo or a worktree of one")

    # Late: the event handlers belong to the dispatcher's package.
    from agent_build_kit.pipeline.events import (
        build_claim,
        build_delete_branch,
        build_remove_worktree,
        build_restack,
        build_retarget,
    )

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
        "claim": build_claim(installation.locks_dir),
        "retarget": build_retarget(),
        "rebase_cap": installation.stack_depth_rebase_cap,
        "lane": lane,
        "resume": thread_resumer(installation, store),
    }


def thread_resumer(inst: Installation, store: UnitStore) -> Callable[..., bool]:
    """Delivers an event to a unit's thread, as the event handlers do: True when it did."""

    def resume(unit, kind, reason, feedback, from_person=False, rework=None) -> bool:
        return (
            resume_thread(
                inst,
                unit,
                kind,
                store=store,
                reason=reason,
                feedback=feedback,
                from_person=from_person,
                rework=rework,
            )
            is not None
        )

    return resume


def dispatch_for(
    inst: Installation,
    store: UnitStore,
    say: Callable[[str], None] = log,
    *,
    lane: Lane | None = None,
) -> Callable[..., bool]:
    """What each poller event is handed to, every write to a repo's `.git` in
    that repo's turn. Also how a merge the poll has not reported yet is recorded."""
    # Late: the event handlers belong to the dispatcher's package.
    from agent_build_kit.pipeline.events import (
        build_base_checks,
        build_base_passes,
        build_base_tip,
        build_dispatch,
        build_fetch_check_logs,
        build_fetch_review,
        build_fork_point,
        build_late_check_turn,
        build_rerun_checks,
    )

    return build_dispatch(
        store,
        repos=inst.checkouts,
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
        base_passes=build_base_passes(
            inst.checkouts,
            unit_test_of=lambda name: build_repo_unit_test(inst, name, log=say),
            turn=lambda name: repo_turn(inst, name),
            log=say,
        ),
        base_checks=build_base_checks(for_repo=inst.forge_of),
        late_turn=build_late_check_turn(inst.locks_dir),
        # A pass polls between builds, so an event may name a unit still
        # building; the handlers leave it to a later poll. See `events`.
        waiting_path=inst.state_dir / "held-waiting.json",
        landing_path=inst.state_dir / landing_intent.LANDING,
        merge_record=lambda unit: merge_record_of(inst, unit),
        log=say,
    )


def merge_record_of(inst: Installation, unit: StoredUnit) -> tuple[str | None, int | None]:
    """The merge commit of a unit just seen merged and the number of the tick that saw it;
    None for what cannot be read (a forge that answers nothing, no tick record yet)."""
    sha = unit.merge_sha
    if sha is None and unit.pr is not None:
        try:
            forge, repo_id = inst.forge_of(unit.repo)
            sha = forge.merge_commit(repo_id, unit.pr)
        except Exception as error:  # noqa: BLE001 — a merge is recorded without its commit.
            log(f"{unit.id}: merge commit unknown — {error}")
    record = loaded_code.current()
    return sha, record.number if record else None


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
    cause = network_probe.classify_reachability(
        error.host,
        network_probe.control_group(inst),
        timeout=limits.network_probe_timeout_seconds,
        api_port=error.port,
    )
    if error.service == "code_host":
        # A git call that never got an answer is parked whatever the probe finds a moment
        # later: the host answering again is why it resumes, not why it did not park. The
        # probe only says whether the whole network is down, or the code host alone.
        return (
            Cause.NETWORK_UNAVAILABLE
            if cause is Cause.NETWORK_UNAVAILABLE
            else Cause.HOST_UNAVAILABLE
        )
    return cause


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
                _clear_starting(store, unit.id)
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
                runner = build_runner(
                    unit,
                    store=store,
                    installation=inst,
                    record_merge=lambda repo, pr: dispatch_for(inst, store)(
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
                    if not dispatch_for(inst, store, lane=lane)(
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
        partial(decide_start, account=account, from_snapshot=True)
        if from_snapshot
        else partial(_start_decision, [account])
    )
    until = pause.until or build_resume_at(start=start)()
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
        orchestration.get(ARTIFACTS, inst),
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
            record_merge=lambda repo, pr: dispatch_for(inst, store)("merged", pr, repo=repo),
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
    from agent_build_kit.graph.unit import advance_through_prepare
    from agent_build_kit.orchestration.checkpoints import open_checkpoints

    make_runner, base, graph = _thread_runner(inst, unit, store, _unit_log(unit))

    async def advance() -> UnitRun | None:
        async with open_checkpoints(inst) as saver:
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


def _validated(inst: Installation, path: Path) -> tuple[list[TaskGroup], list[ValidationError]]:
    """A tasks file's groups and errors against the installation's repos and their projects."""
    return validate_tasks(path, **_validation_scope(inst))


def _validation_scope(inst: Installation) -> dict[str, Any]:
    """The repos, projects and e2e-test splits the installation declares, as `validate_tasks`
    and `validate_tasks_text` take them."""
    return {
        "repos": tuple(inst.repos),
        "projects": declared_projects(inst.repos),
        "splits": declared_split_names(inst.repos, inst.config),
        "project_profiles": declared_profiles(inst.repos),
    }


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
    from agent_build_kit.graph.unit import resume_unit, run_unit
    from agent_build_kit.orchestration.checkpoints import open_checkpoints

    common = dict(base=base, graph=graph, run_log=run_log, tracer=telemetry.tracer())
    async with open_checkpoints(inst) as saver:
        if event is None:
            # Under the lock `build_unit` holds; a delivery takes its own.
            return await run_unit(runner, unit, saver=saver, **common)
        return await resume_unit(
            runner,
            unit,
            saver=saver,
            event=event,
            feedback=feedback,
            locks=inst.locks_dir,
            **common,
        )
