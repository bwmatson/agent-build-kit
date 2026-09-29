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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import diagram
from agent_build_kit.pipeline.archive import (
    _already_archived,
    archive_ready_changes,
    is_ready_to_archive,
)
from agent_build_kit.pipeline.events import (
    build_delete_branch,
    build_dispatch,
    build_fetch_check_logs,
    build_fetch_review,
    build_remove_worktree,
    build_restack,
)
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.gh_poller import Poller
from agent_build_kit.pipeline.pause import clear_pause, is_paused, pause_until
from agent_build_kit.pipeline.planner import plan_round
from agent_build_kit.pipeline.pr_replies import own_posts
from agent_build_kit.pipeline.shell import gh, git
from agent_build_kit.pipeline.tier2 import stack_lock
from agent_build_kit.pipeline.unit_store import UNPLANNED, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    IN_FLIGHT,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    Unit,
    base_of,
    branch_name,
    ready_units,
)
from agent_build_kit.pipeline.usage_guard import (
    Interrupted,
    RateLimited,
    current_usage,
    may_start_unit,
)
from agent_build_kit.pipeline.verify import Verification, VerifyRecord, verify_change
from agent_build_kit.pipeline.wiring import build_commit, build_runner
from agent_build_kit.pipeline.work_graph import NEEDS_LINE, cross_change_needs, validate_tasks
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_lock, worktree_path


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


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


def cmd_status(args: argparse.Namespace, inst: Installation) -> int:
    """What the pipeline thinks is going on, without changing anything."""
    paused = is_paused(_paused_marker(inst))
    if paused:
        log(f"paused until {paused.until:%Y-%m-%d %H:%M UTC} — {paused.reason}")

    reading = current_usage()
    if reading:
        log(
            f"usage: session {reading.session_pct}%, weekly {reading.weekly_pct}% "
            f"({reading.source})"
        )
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
    result = gh(
        ["gh", "pr", "view", str(pr), "--repo", inst.slug(repo), "--json", "files",
         "--jq", ".files[].path"]
    )  # fmt: skip
    if result.returncode:
        raise RuntimeError(f"gh pr view {pr} ({repo}): {result.stderr.strip()}")
    return result.stdout.split()


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
    specs_dir = inst.config.planning.specs_dir
    changes = {
        u.change
        for u in units
        if is_ready_to_archive(u.change, units)
        and not _already_archived(u.change, inst.root, specs_dir)
    }
    for change in sorted(changes):
        merged = sorted(u.id for u in units if u.change == change and u.state == MERGED)
        last = record.get(change)
        if last is not None and last.units == merged:
            continue
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
    fetch_all(inst)

    try:
        poll_all(inst, store=store)
    except Exception as error:  # noqa: BLE001
        # GitHub being unreachable is a reason to skip the update, not to stop
        # building units whose work doesn't depend on it.
        log(f"poll skipped — {type(error).__name__}: {error}")

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
    )
    for change in archived:
        log(f"archived {change}")

    ready = ready_units(
        list(units),
        max_concurrent=inst.max_concurrent_stacks,
        depth_cap=inst.stack_depth_cap,
    )
    if only := getattr(args, "only", None):
        # Everything else still happens — polling, planning, archiving — so
        # the store stays current; only building is narrowed. For pushing one
        # unit through when usage is tight, without a second competing for it.
        held_back = [unit.id for unit in ready if unit.id not in only]
        ready = [unit for unit in ready if unit.id in only]
        if held_back:
            log(f"--only: not building {', '.join(held_back)}")
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
    unconfigured = [repo for repo in {unit.repo for unit in ready} if not _has_identity(inst, repo)]
    if unconfigured:
        log(
            f"refusing to build: {', '.join(sorted(unconfigured))} has no repo-local "
            "user.email, so agent commits would fall back to this machine's global "
            "identity instead of the account that owns the repo. Set it with "
            "`git -C <repo> config user.email <account>@users.noreply.github.com`."
        )
        return 1

    # All at once. `ready_units` has already applied the concurrency cap and
    # the dependency rules, so every unit here is independent of the others
    # and there is no reason for one to wait on another's hour-long build.
    # A pause in one does not stop the rest: they have already started, and
    # each checks the usage guard itself before its first Claude run.
    with ThreadPoolExecutor(max_workers=len(ready), thread_name_prefix="unit") as pool:
        list(pool.map(lambda unit: _build(inst, unit, store=store, graph=list(units)), ready))
    return 0


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
        # rejects, leaving the change unplannable.
        context = [
            {"id": u.id, "repo": u.repo, "branch": u.branch, "state": u.state}
            for u in store.all()
            if u.state in (*IN_FLIGHT, MERGED)
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
                if u.change == change and u.state in (*IN_FLIGHT, MERGED)
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
    """Whether a tick has anything to do: a unit in progress, or a change
    whose tasks.md has not been planned in its current form."""
    if any(unit.state in NEEDS_TICKS for unit in store.all()):
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
    """Whether `repo` says who its commits belong to, rather than inheriting.

    The agent commits as whoever the repo is configured for — the same
    identity the developer uses there — so there is nothing for the pipeline
    to override. What it must not do is fall through to the machine's global
    identity, which may belong to neither account.
    """
    path = inst.checkouts.get(repo)
    if path is None:
        return False

    return bool(git(path, "config", "--local", "user.email", check=False).stdout.strip())


def fetch_all(inst: Installation) -> None:
    """Bring each code repo's remote refs up to date. See `units.local_ref`.

    Only remote-tracking refs move: the checkout's own branches are the
    user's, and are left exactly where they are.
    """
    for repo, path in inst.checkouts.items():
        with file_lock(inst.state_dir / "locks" / f"repo-{repo}.lock"):
            result = git(path, "fetch", "-q", "--prune", "origin", check=False)
        if result.returncode:
            why = result.stderr.strip()
            log(f"fetch of {repo} failed — building on what it last fetched: {why}")


def poll_all(inst: Installation, *, store: UnitStore) -> None:
    """Ask GitHub what changed in each repo, and act on it.

    One poller per repo, each with its own recorded state, so a failure in one
    doesn't replay the other's history. The first poll of a repo records
    without dispatching — a fresh state file must not look like a hundred
    simultaneous merges.
    """
    checkouts = inst.checkouts
    dispatch = build_dispatch(
        store,
        restack=build_restack(
            repos=checkouts, store=store, root=inst.worktree_root, posts_root=inst.state_dir
        ),
        remove_worktree=build_remove_worktree(checkouts, root=inst.worktree_root),
        delete_branch=build_delete_branch(checkouts),
        fetch_review=build_fetch_review(checkouts),
        fetch_checks=build_fetch_check_logs(),
        log=log,
    )

    for repo in checkouts:
        slug = inst.slug(repo)
        Poller(
            repo=slug,
            state_path=inst.state_dir / f"prs-{repo}.json",
            dispatch=dispatch,
            ignore=lambda number, slug=slug: own_posts(inst.state_dir, slug, number),
        ).poll()


def _build(inst: Installation, unit: Unit, *, store: UnitStore, graph: list[StoredUnit]) -> bool:
    """Build one unit. Returns False only when the tick should stop entirely.

    Nothing in here may raise. A tick runs unattended on a timer, so a
    traceback is not a report — it is a unit left in `running` forever and no
    log line saying which one.
    """
    branch = branch_name(unit)
    try:
        with branch_lock(branch, root=inst.state_dir / "locks"):
            # Re-read under the lock. `ready` was worked out when the tick
            # started, and ticks overlap to build in parallel: by the time this
            # one reaches a unit, another may have built it and opened its PR.
            # Building it again would re-verify, re-push and re-open that PR.
            current = store.get(unit.id).state
            if current != PLANNED:
                log(f"{unit.id}: skipped, another tick has taken it ({current})")
                return True
            runner = build_runner(
                unit,
                store=store,
                installation=inst,
                log=lambda message: log(f"{unit.id}: {message}"),
            )
            outcome = runner.run(unit, base=base_of(unit, list(graph)), graph=graph)
    except NotImplementedError as error:
        # A toolchain profile the framework does not implement yet: not the
        # unit's fault, and nothing a retry changes. Held for a person.
        log(f"{unit.id}: held — {error}")
        store.set_state(unit.id, "held", note=str(error))
        return True
    except Interrupted as error:
        # Left `running`, with the lock released as the `with` exits: the next
        # tick's `reclaim_stale` commits what the run left and requeues it at
        # the step it was in. Not failed — nothing is known to be wrong.
        log(f"{unit.id}: interrupted ({error}); the next tick reclaims it")
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
        log(f"{unit.id}: rate limited — pausing until {state.until:%H:%M UTC}")
        return False
    except BranchBusy as error:
        # Another tick is already on it. Not a failure — marking it one would
        # drop a unit that is going fine out of the plan.
        log(f"{unit.id}: skipped, {error}")
        return True
    except Exception as error:  # noqa: BLE001 — see the docstring.
        log(f"{unit.id}: failed, {type(error).__name__}: {error}")
        try:
            store.set_state(unit.id, "failed")
        except Exception as second:  # noqa: BLE001
            log(f"{unit.id}: could not be recorded as failed — {second}")
        return True

    log(f"{unit.id}: {outcome.status} — {outcome.detail}")
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
