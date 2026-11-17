"""What the dispatcher and the worker both call to run a unit: the store, the threads,
the event handlers' wiring and the start decision."""

from __future__ import annotations

import asyncio
from collections.abc import (
    Callable,
    Sequence,
)
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from agent_build_kit import (
    claude_account,
    orchestration,
    profiles,
    telemetry,
)
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.orchestration.artifacts import INTERFACE as ARTIFACTS
from agent_build_kit.pipeline import (
    demotion_triggers,
    diagram,
    landing_intent,
    loaded_code,
    network_probe,
    usage_report,
)
from agent_build_kit.pipeline.demotion_record import DEMOTIONS
from agent_build_kit.pipeline.drafts import StateDrafts
from agent_build_kit.pipeline.e2e_holds import (
    split_gates,
)
from agent_build_kit.pipeline.file_lock import (
    file_lock,
)
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.pause import (
    Pause,
    pause_for,
    pause_in_force,
    pause_line,
    pause_marker,
)
from agent_build_kit.pipeline.planning_repo import (
    repo_sharing,
)
from agent_build_kit.pipeline.pr_poller import (
    recorded_checks,
)
from agent_build_kit.pipeline.restack import (
    ConflictSession,
    Moved,
    checked_out_at,
    push_with_lease,
    resolved_move,
)
from agent_build_kit.pipeline.run_log import (
    RunLog,
    run_ledger_path,
)
from agent_build_kit.pipeline.stack_runner import (
    RunOutcome,
    RunStatus,
    UnitRunner,
)
from agent_build_kit.pipeline.ui_review import (
    ui_notes_of,
    unit_patch_of,
)
from agent_build_kit.pipeline.unit_store import (
    Cause,
    RequeueReason,
    ReworkKind,
    StoredUnit,
    UnitStore,
    feedback_source_of,
)
from agent_build_kit.pipeline.units import (
    HELD,
    MERGED,
    PLANNED,
    RUNNING,
    Unit,
    UnitState,
    base_of,
    branch_name,
)
from agent_build_kit.pipeline.usage_forecast_ask import Ask
from agent_build_kit.pipeline.usage_guard import (
    Decision,
    ask_before_call,
    current_usage,
    decide_start,
    may_start_unit,
    starting,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from agent_build_kit.pipeline.wiring import (
    Run,
    build_on_flake,
    build_runner,
    build_unit_test,
    build_usage_gate,
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
    worktree_key,
)
from agent_build_kit.redaction import redact_text
from agent_build_kit.runtimes import AgentRateLimited, NetworkUnavailable

if TYPE_CHECKING:
    from agent_build_kit.graph.state import ResumeEvent
    from agent_build_kit.graph.unit import Position
    from agent_build_kit.pipeline.events import Restack
    from agent_build_kit.pipeline.resolution_lane import Lane


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
    catalog = task_catalog(inst)
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


def paused_marker(inst: Installation, account: claude_account.Account) -> Path:
    """The marker of `account`'s pause: the default account's is also the network's."""
    return pause_marker(inst.state_dir, account)


def paused_for(inst: Installation, unit: StoredUnit | Unit) -> Pause | None:
    """The pause in force for the unit's own account: its marker's, or a network outage."""
    return pause_for(inst.state_dir, claude_account.for_repo(inst.config, unit.repo))


def pause_report(inst: Installation, pause: Pause, *, verb: str = "paused") -> str:
    """`pause_line`, naming the account and kind of a pause when the installation keeps accounts
    apart. A network pause is the whole installation's, so it names none."""
    line = pause_line(pause, verb=verb)
    if pause.kind == "network" or not (
        pause.account or claude_account.slots_per_account(inst.config)
    ):
        return line
    return f"account {pause.account or 'default'} ({pause.kind}): {line}"


def demote_failed_verify(inst: Installation, change: str, units: list) -> None:
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
    # Late: the lane's record reader is the worker's until the lane records move to the core.
    from agent_build_kit.pipeline.resolution_lane import lane_record

    return {entry["unit"]: entry["base"] for entry in lane_record(inst.state_dir)}


def merged_ids(change: str, units: list) -> list[str]:
    # The same rule `verify_change` records its units by: a merged unit with a PR.
    return sorted(u.id for u in units if u.carries(change) and u.state == MERGED and u.pr)


def decision_key(
    account: claude_account.Account, tier: ReviewTier | None, lines: int, *, plan_due: bool = False
) -> str:
    """Where `decided` keeps the decision for a start of this tier and size on `account`: units
    of one tier and size are asked of the guard once. A start that reserves the plan call is not
    the start a unit's gate asks for, so it is kept apart."""
    return f"{claude_account.account_key(account)}|{tier}|{lines}|{plan_due}"


def account_decision(
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
        decision_key(account, named.tier, named.lines, plan_due=named.plan_due)
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


def start_decision(
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
        decision = account_decision(account, decided, ask)
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


def clear_starting(store: UnitStore, unit_id: str) -> None:
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
        and paused_for(inst, unit) is not None
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


def task_catalog(inst: Installation) -> dict[str, tuple[TaskGroup, ...]]:
    """Every change's task groups, as `unit_priority` and the plan check read them."""
    return {path.parent.name: tuple(validated(inst, path)[0]) for path in inst.tasks_files()}


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
        paused=lambda unit: paused_for(inst, unit) is not None,
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


def outage_cause(inst: Installation, error: NetworkUnavailable) -> Cause | None:
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


def unit_log(unit: StoredUnit) -> Callable[[str], None]:
    def say(message: str) -> None:
        log(f"{unit.id}: {message}")

    return say


def thread_runner(
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
    from agent_build_kit.graph.state import EventKind, ResumeEvent
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
    say = unit_log(unit)
    try:
        make_runner, base, graph = thread_runner(inst, unit, store, say)
        runner = make_runner()
        store.record_step(unit.id, "")
        outcome = asyncio.run(
            on_thread(
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


def validated(inst: Installation, path: Path) -> tuple[list[TaskGroup], list[ValidationError]]:
    """A tasks file's groups and errors against the installation's repos and their projects."""
    return validate_tasks(path, **validation_scope(inst))


def validation_scope(inst: Installation) -> dict[str, Any]:
    """The repos, projects and e2e-test splits the installation declares, as `validate_tasks`
    and `validate_tasks_text` take them."""
    return {
        "repos": tuple(inst.repos),
        "projects": declared_projects(inst.repos),
        "splits": declared_split_names(inst.repos, inst.config),
        "project_profiles": declared_profiles(inst.repos),
    }


async def on_thread(
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
