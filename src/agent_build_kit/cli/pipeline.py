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
import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import diagram
from agent_build_kit.pipeline.archive import (
    _already_archived,
    archive_ready_changes,
    is_ready_to_archive,
)
from agent_build_kit.pipeline.events import (
    build_claim,
    build_delete_branch,
    build_dispatch,
    build_fetch_check_logs,
    build_fetch_review,
    build_remove_worktree,
    build_restack,
    build_retarget,
)
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.pause import clear_pause, is_paused, pause_until
from agent_build_kit.pipeline.planner import GroupTooLarge, plan_round
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.pr_replies import own_posts
from agent_build_kit.pipeline.restack import push_with_lease, resolved_move
from agent_build_kit.pipeline.run_log import RunLog, remove_change_logs, run_log_dir
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.stack_runner import starting_step
from agent_build_kit.pipeline.tier2 import stack_lock
from agent_build_kit.pipeline.unit_store import UNPLANNED, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    HELD,
    IN_FLIGHT,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    Unit,
    base_of,
    branch_name,
    ready_units,
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
from agent_build_kit.pipeline.verify import Verification, VerifyRecord, verify_change
from agent_build_kit.pipeline.wiring import CommitRejected, build_commit, build_runner
from agent_build_kit.pipeline.work_graph import NEEDS_LINE, cross_change_needs, validate_tasks
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_lock, worktree_path


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

    return UnitStore(inst.state_dir / "units.json", on_write=refresh_graph)


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

    reading = current_usage()
    if reading:
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

    for unit in units:
        if unit.state == IN_REVIEW:
            log(f"  awaiting review: {unit.id} ({unit.repo}) #{unit.pr or '?'}")
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
    return sorted(u.id for u in units if u.change == change and u.state == MERGED and u.pr)


def _unverified(inst: Installation, units: list, record: VerifyRecord) -> list[str]:
    """Changes ready to archive, not archived, and with no verification on
    record over their current merged units."""
    specs_dir = inst.config.planning.specs_dir
    changes = {
        u.change
        for u in units
        if is_ready_to_archive(u.change, units)
        and not _already_archived(u.change, inst.root, specs_dir)
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
    ):
        print(f"archived {change}")
    return 0


# --- the tick ---------------------------------------------------------------------------


def cmd_tick(args: argparse.Namespace, inst: Installation) -> int:
    """One pass of the loop. Safe to call at any time.

    Ordering matters in one place: the usage check comes first, so a low
    window stops the tick before it spends anything on planning.
    """
    # First, and silently: the timer fires every few minutes whether or not
    # there is anything to do, and an idle tick should cost nothing — not a
    # usage read, not a GitHub call, not a log line each time.
    if not has_work(inst, store_for(inst)):
        return 0

    paused = is_paused(_paused_marker(inst))
    if paused:
        log(f"paused until {paused.until:%H:%M UTC} — {paused.reason}")
        return 0

    reading = current_usage()
    decision = may_start_unit(reading)
    if not decision.may_start:
        state = pause_until(
            reading.resets_at if reading else None,
            reason=decision.reason,
            marker=_paused_marker(inst),
        )
        log(f"pausing until {state.until:%H:%M UTC} — {decision.reason}")
        return 0

    clear_pause(_paused_marker(inst))
    log(decision.reason)

    store = store_for(inst)

    # Before anything is scheduled: a PR that merged since the last tick frees
    # a depth slot and changes what the branches above it should sit on, so
    # planning against the pre-poll graph builds against a stale picture.
    # Before polling: a merge the poll finds restacks the units above it
    # straight away, and they must land on the trunk as it now is.
    _refresh(inst, store=store)

    reclaim_stale(inst, store=store)
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
    )
    for change in archived:
        log(f"archived {change}")

    # Everything else still happens — polling, planning, archiving — so the
    # store stays current; only building is narrowed. For pushing one unit
    # through when usage is tight, without a second competing for it.
    only = frozenset(getattr(args, "only", None) or ())
    if only:
        log(f"--only: building nothing but {', '.join(sorted(only))}")
    ready = _evaluate(inst, units, started=set(), building=set(), only=only)
    if not ready:
        log("nothing ready to build")
        return 0

    log(f"ready: {', '.join(unit.id for unit in ready)}")
    if args.dry_run:
        log("dry run — stopping before any unit is built")
        return 0

    # Here rather than at the commit step: catching it there would mean
    # paying for two Claude runs first, and again every tick. After the dry
    # run returns, so `--dry-run` still reports what is pending.
    if _refuse_unconfigured(inst, ready):
        return 1

    return _schedule(inst, ready, store=store, only=only)


def _evaluate(
    inst: Installation,
    units: list[StoredUnit],
    *,
    started: set[str],
    building: set[str],
    only: frozenset[str],
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
        view, max_concurrent=inst.max_concurrent_stacks, depth_cap=inst.stack_depth_cap
    )
    return [unit for unit in ready if unit.id not in started]


def _refuse_unconfigured(inst: Installation, ready: list[Unit]) -> bool:
    unconfigured = [repo for repo in {unit.repo for unit in ready} if not _has_identity(inst, repo)]
    if unconfigured:
        log(
            f"refusing to build: git has no identity for {', '.join(sorted(unconfigured))}, "
            "so an agent's commits would be attributed to nobody. Set one globally with "
            "`git config --global user.email <email>` (and user.name), or for this repo "
            "alone with `git -C <repo> config user.email <email>`."
        )
    return bool(unconfigured)


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
    started: set[str] = set()
    building: dict[Future[bool], Unit] = {}
    stopping = False
    refused = False
    with ThreadPoolExecutor(
        max_workers=inst.max_concurrent_stacks, thread_name_prefix="unit"
    ) as pool:

        def submit(units: list[Unit]) -> None:
            for unit in units:
                started.add(unit.id)
                building[pool.submit(_build, inst, unit, store=store)] = unit

        submit(ready)
        # Driven by completions, not a timer: each round blocks until a build
        # finishes, and the pass ends once none is in flight.
        while building:
            done, _ = wait(building, return_when=FIRST_COMPLETED)
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
            ready = _evaluate(
                inst,
                store.all(),
                started=started,
                building={unit.id for unit in building.values()},
                only=only,
            )
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


def _branch_is_held(inst: Installation, branch: str) -> bool:
    """Whether a live process holds this branch's lock.

    `branch_lock` already distinguishes a crashed holder from a live one by
    its pid; acquiring and releasing is the cheapest way to ask.
    """
    try:
        with branch_lock(branch, root=inst.state_dir / "locks"):
            return False
    except BranchBusy:
        return True


def _commit_leftovers(inst: Installation, unit: Unit) -> int:
    """Commit whatever the killed run had written but not committed.

    Without this the reclaim is hollow: `prepare_worktree` refuses a dirty
    tree, so the unit goes back to `planned` in a state it cannot start from.
    The work is the agent's own — these worktrees have no other writer — and
    the next run's `git add -A` would have swept it into the tests commit
    regardless, so committing it loses nothing and makes the tree reusable.
    """
    repo = inst.checkouts.get(unit.repo)
    if repo is None:
        return 0

    tree = worktree_path(repo, branch_name(unit), inst.worktree_root)
    if not tree.exists():
        return 0

    made = build_commit(unit_id=unit.id)(f"wip: {unit.title} (interrupted run)", cwd=tree)
    if made:
        log(f"{unit.id}: committed work the interrupted run had left uncommitted")
    return made


def reclaim_stale(inst: Installation, *, store: UnitStore) -> None:
    """Put units back that nothing is working on any more.

    `ready_units` only ever picks up `planned`, so a unit left `running` when
    its tick was killed would be stranded for good. Reclaimed at the start of
    a tick and nowhere else: this is the "at startup" recovery, not a retry
    timer, and a unit that keeps failing on its own merits still stops at
    `failed`.

    A unit whose branch lock a live process holds is left alone. Ticks can
    overlap — a slow unit outlives the timer interval — and reclaiming one
    would hand the same work to a second runner.
    """
    for unit in store.all():
        if unit.state != RUNNING:
            continue
        branch = unit.branch or branch_name(unit)
        if _branch_is_held(inst, branch):
            continue
        log(f"{unit.id}: reclaimed — left running with no process on it")
        if _commit_leftovers(inst, unit) and not (unit.resume_from or unit.feedback):
            # Those leftovers are commits now, and the resume path reads
            # commits on the branch as "the work is there" and skips building
            # — which would send an interrupted unit straight to tier 1 on
            # half-written work. Saying so as feedback routes it to the rework
            # path, which continues from what is there.
            #
            # Only when nothing better is known. A unit that recorded the step
            # it was in resumes there, and feedback already waiting is what
            # review asked for — replacing it would lose the review.
            store.set_feedback(
                unit.id,
                "The previous run was interrupted partway through and its work was "
                "committed as-is. Continue from what is on the branch: finish the "
                "tasks, keeping anything already written that still makes sense.",
            )
        store.set_state(unit.id, PLANNED, note="reclaimed: no process held its branch")


def link_needs(inst: Installation, *, store: UnitStore) -> None:
    """Apply every change's `Needs:` lines as unit dependencies.

    Every tick, after planning: a re-plan takes each unit's dependencies from
    the plan, which knows nothing of these, so linking once would not last.
    Idempotent — a dependency already there is left alone.
    """
    units = store.all()
    covering = {
        (unit.change, group): unit.id
        for unit in units
        if unit.state != UNPLANNED
        for group in unit.groups
    }
    for tasks in inst.tasks_files():
        change = tasks.parent.name
        for group, needs in cross_change_needs(tasks).items():
            wanted = [covering[need] for need in needs if need in covering]
            for missing in (need for need in needs if need not in covering):
                log(
                    f"{change} group {group} needs {missing[0]} group {missing[1]}, not planned yet"
                )
            for unit in units:
                if unit.change != change or group not in unit.groups or unit.state == UNPLANNED:
                    continue
                linked = tuple(dict.fromkeys((*unit.depends_on, *wanted)))
                if linked != unit.depends_on:
                    store.set_dependencies(unit.id, linked)
                    log(f"{unit.id}: now depends on {', '.join(wanted)} (Needs: in tasks.md)")


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
        digest = hashlib.sha256(_specification(tasks).encode()).hexdigest()
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
        context = [
            {"id": u.id, "repo": u.repo, "branch": u.branch, "state": u.state}
            for u in store.all()
            if u.state in (*IN_FLIGHT, MERGED, SATISFIED)
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
            built = {
                number
                for u in store.all()
                if u.change == change and u.state in (*IN_FLIGHT, MERGED, SATISFIED)
                for number in u.groups
            }
            units = plan_round(
                changes={change: tasks.read_text()},
                in_flight=context,
                groups=task_groups,
                built=built,
                # Units the store already has: a dependency naming one of
                # them is not a dependency on nothing.
                known={u.id for u in store.all()},
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

        store.upsert(units, change=change)
        planned[change] = {"hash": digest, "attempts": 0, "ok": True}
        _write_planned(inst, planned)
        log(f"planned {change}: {len(units)} unit(s)")


# "- [x] 1.1 ..." and "- [ ] 1.1 ..." are the same specification at different
# stages of being carried out.
CHECKBOX = re.compile(r"^(\s*-\s*\[)[ xX](\])", re.MULTILINE)


def _specification(tasks: Path) -> str:
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
        if any(u.change in waiting for u in satisfied):
            return True
    planned = _planned_hashes(inst)
    for tasks in inst.tasks_files():
        record = planned.get(tasks.parent.name) or {}
        digest = hashlib.sha256(_specification(tasks).encode()).hexdigest()
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


def _has_identity(inst: Installation, repo: str) -> bool:
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
        with _repo_turn(inst, repo):
            result = git(path, "fetch", "-q", "--prune", "origin", check=False)
        if result.returncode:
            why = result.stderr.strip()
            log(f"fetch of {repo} failed — building on what it last fetched: {why}")


def _repo_turn(inst: Installation, repo: str) -> AbstractContextManager[None]:
    """The turn a repo's `.git` is taken by, the one `build_runner` takes
    around a build's worktree add and push: git's own locks there fail
    rather than wait."""
    return file_lock(inst.state_dir / "locks" / f"repo-{repo}.lock")


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
    names = {path: repo for repo, path in checkouts.items()}

    def named[T](step: Callable[..., T]) -> Callable[..., T]:
        def in_turn(repo: str, *args, **kwargs) -> T:
            with _repo_turn(inst, repo):
                return step(repo, *args, **kwargs)

        return in_turn

    def at_path[T](step: Callable[..., T]) -> Callable[..., T]:
        def in_turn(path: Path, *args, **kwargs) -> T:
            with _repo_turn(inst, names[path]):
                return step(path, *args, **kwargs)

        return in_turn

    dispatch = build_dispatch(
        store,
        restack=build_restack(
            repos=checkouts,
            store=store,
            root=inst.worktree_root,
            posts_root=inst.state_dir,
            move=at_path(resolved_move),
            push=at_path(push_with_lease),
        ),
        remove_worktree=named(build_remove_worktree(checkouts, root=inst.worktree_root)),
        delete_branch=named(build_delete_branch(checkouts)),
        fetch_review=build_fetch_review(),
        fetch_checks=build_fetch_check_logs(),
        # A pass polls between builds, so an event may name a unit still
        # building; the handlers leave it to a later poll. See `events`.
        claim=build_claim(inst.state_dir / "locks"),
        retarget=build_retarget(),
        log=log,
    )

    for repo in checkouts:
        forge, repo_id = inst.forge_of(repo)
        # The identity as one string: what `own-posts.json` has always been
        # keyed on, so an installation keeps its record of its own comments.
        slug = forges.key(repo_id)
        Poller(
            repo=slug,
            state_path=inst.state_dir / f"prs-{repo}.json",
            # Bound to this repo: the poller reports a bare number, and a
            # number names a unit only together with the repo it was read from.
            dispatch=lambda event, number, repo=repo, **kwargs: dispatch(
                event, number, repo=repo, **kwargs
            ),
            list_prs=lambda forge=forge, repo_id=repo_id: forge.list_prs(repo_id),
            ignore=lambda number, slug=slug: own_posts(inst.state_dir, slug, number),
        ).poll()


def _build(inst: Installation, unit: Unit, *, store: UnitStore) -> bool:
    """Build one unit. Returns False only when the tick should stop entirely.

    Nothing in here may raise. A tick runs unattended on a timer, so a
    traceback is not a report — it is a unit left in `running` forever and no
    log line saying which one.
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

    def end(message: str) -> None:
        nonlocal ended
        ended = message
        say(message)

    try:
        try:
            with branch_lock(branch, root=inst.state_dir / "locks"):
                # Re-read under the lock. `ready` comes from the pass's latest
                # evaluation, and ticks overlap to build in parallel: by the time
                # this one reaches a unit, another may have built it and opened its
                # PR. Building it again would re-verify, re-push and re-open that
                # PR. A poll may also have held or closed it since.
                current = store.get(unit.id).state
                if current != PLANNED:
                    end(f"skipped, it is now {current}")
                    return True
                # The base too, from the store rather than that evaluation: a
                # parent may have merged since, and `base_moved` compares against
                # this.
                graph = store.all()
                base = base_of(unit, graph)
                step, model = starting_step(store.get(unit.id))
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
                runner = build_runner(unit, store=store, installation=inst, log=say)
                outcome = runner.run(unit, base=base, graph=graph)
        except NotImplementedError as error:
            # A toolchain profile the framework does not implement yet: not the
            # unit's fault, and nothing a retry changes. Held for a person.
            end(f"held — {error}")
            store.set_state(unit.id, "held", note=str(error))
            return True
        except Interrupted as error:
            # Left `running`, with the lock released as the `with` exits: the next
            # tick's `reclaim_stale` commits what the run left and requeues it at
            # the step it was in. Not failed — nothing is known to be wrong.
            end(f"interrupted ({error}); the next tick reclaims it")
            return True
        except RateLimited as error:
            # Not the unit's fault and not retried: the account is out of room, so
            # marking it failed would drop real work from the plan, and trying the
            # next unit would spend a call to be told the same thing.
            when = error.resets_at
            if when is None:
                reading = current_usage()
                when = reading.resets_at if reading else None

            state = pause_until(
                when, reason=f"rate limited during {unit.id}", marker=_paused_marker(inst)
            )
            end(f"rate limited — pausing until {state.until:%H:%M UTC}")
            return False
        except BranchBusy as error:
            # Another tick is already on it. Not a failure — marking it one would
            # drop a unit that is going fine out of the plan.
            end(f"skipped, {error}")
            return True
        except Exception as error:  # noqa: BLE001 — see the docstring.
            end(f"failed, {type(error).__name__}: {error}")
            # A rejected commit's reason is the gate's own output: on the unit's
            # record, not only in a tick log someone would have to find.
            note = str(error) if isinstance(error, CommitRejected) else ""
            try:
                store.set_state(unit.id, "failed", note=note)
            except Exception as second:  # noqa: BLE001
                say(f"could not be recorded as failed — {second}")
            return True

        end(f"{outcome.status} — {outcome.detail}")
        if outcome.status == "paused":
            # Re-read rather than reuse the tick's reading: the guard said no
            # after the units before this one ran, so the window has moved, and a
            # resume scheduled from the stale figure wakes up into a full window.
            reading = current_usage()
            state = pause_until(
                reading.resets_at if reading else None,
                reason=outcome.detail,
                marker=_paused_marker(inst),
            )
            log(f"pausing until {state.until:%H:%M UTC}")
            return False
        return True
    finally:
        if run_log is not None:
            run_log.close(ended)


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


def cmd_gate(args: argparse.Namespace, inst: Installation | None) -> int:
    """The push gate, for a branch in a checkout: tests-first order, clean
    and red at the tests commit."""
    from agent_build_kit import profiles
    from agent_build_kit.pipeline.check_runner import CheckCache
    from agent_build_kit.pipeline.gate import check_branch

    profile_name = args.profile
    if inst is not None and profile_name is None:
        repo = Path(args.repo).resolve()
        for name, path in inst.checkouts.items():
            if repo == path.resolve() or repo.is_relative_to(path.resolve()):
                profile_name = inst.repo(name).profile
                break
    profile = profiles.get(profile_name or "python-uv")
    cache = CheckCache(args.cache) if args.cache else None
    problems = check_branch(Path(args.repo), args.base, cache=cache, profile=profile)
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

    archive = sub.add_parser("archive", help="openspec archive <change> --yes")
    archive.add_argument("change")
    archive.set_defaults(func=cmd_archive)

    passthrough = sub.add_parser("openspec", help="run any OpenSpec command in the planning repo")
    passthrough.add_argument("args", nargs=argparse.REMAINDER)
    passthrough.set_defaults(func=cmd_openspec)

    gate = sub.add_parser("gate", help="the push gate for a unit's branch")
    gate.add_argument("--repo", type=Path, default=Path.cwd())
    gate.add_argument("--base", default="main", help="branch this unit stacks on")
    gate.add_argument("--cache", type=Path, default=None)
    gate.add_argument("--profile", default=None, help="toolchain profile (default: from abk.yaml)")
    gate.set_defaults(func=cmd_gate, needs_installation="optional")
