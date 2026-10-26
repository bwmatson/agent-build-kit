## Context

Written against agent-build-kit `origin/main` (`f9f53b4c`). The fix makes the three readings of a dependency agree and keeps a stale edge from
lasting. The notice is general because the same blind spot exists on other paths.

## The mismatch

| Reader | File | Test on a same-repo parent | A parent `unplanned` or `retired` |
|---|---|---|---|
| Scheduler, `waiting_on` | `pipeline/units.py` ~704 | skips `BUILDS_NOTHING`, then waits unless `REVIEWED` | does not wait |
| Build guard, `build_upstream_incomplete` | `pipeline/wiring.py` ~3297 | `parent.state not in REVIEWED` | holds the unit: "went back" |
| `why_branch_is_changing` | `pipeline/wiring.py` ~3317 | returns "" only for `REVIEWED` | falls through: changing when its branch head differs from `pushed` |
| `follow_predecessors` | `pipeline/wiring.py` ~3369 | asks `why_branch_is_changing` for each same-repo parent | as above |
| `_parent_went_back` | `pipeline/units.py` ~890 | a parent whose history has a state outside `REVIEWED` since the unit last changed | a once-unplanned parent counts, even if now settled |

`BUILDS_NOTHING = (UNPLANNED, RETIRED)` (`units.py` ~78) is the one definition of "builds nothing". Every fix uses it; none copies the tuple.

## Why a number resolves to different units

`declared_needs` resolves `Needs: <change> group N` through the units that cover the group *now* (`link_needs` passes only units not in
`BUILDS_NOTHING`). A replan can join, split or renumber groups, so group N is carried by unit X when a unit starts and by unit Y after the replan; X
is `unplanned` (or retired by a person). `link_needs` adds the edge to Y, and prunes only the listed dependencies an added target reaches; it does not
look at an edge whose target now builds nothing. A replan replaces an unstarted unit's dependencies with the plan's but "never changes" a started
unit's (main spec, "A replan clears a stale planner edge and leaves started units alone"). So a started unit keeps the edge to X indefinitely.

## Decisions

### The guard skips a parent that builds nothing (a)

In `upstream_incomplete`, the test becomes `parent.repo == unit.repo and parent.state not in BUILDS_NOTHING and parent.state not in REVIEWED`. A
parent in `planned`, `running`, `failed`, `held` or `closed` still holds the child, as before. (`closed` is not in `BUILDS_NOTHING`; it is a finished
state that `waiting_on` also treats as unmet for a same-repo parent, so the two readings still agree.)

### The other sites (b)

- `why_branch_is_changing`: needs it. The first line returns "" for `REVIEWED`; it returns "" for `BUILDS_NOTHING` too. This covers `follow_predecessors`
  through its one call, so the loop itself needs no second test.
- `follow_predecessors`: no second change beyond the above; a test shows a unit in review with an `unplanned` parent whose branch has a commit beyond
  `pushed` stays in review.
- `_parent_went_back`: needs the skip, but on the parent's *current* state: `if parent is None or parent.state in BUILDS_NOTHING: continue`, mirroring
  `waiting_on`. Its history reading is untouched for a live parent.
- Checked and left: `cli/pipeline.py` ~1885, `waiting_on` (the reference), `base_of` (only `IN_REVIEW` parents), `earlier_units` (already excludes `BUILDS_NOTHING`).
- UNVERIFIED: whether `effective_state(parent, graph)` can read `rebasing` for an `unplanned` parent; the skip comes first, so it does not matter.

### The edge is dropped by `link_needs` (c)

Where: `link_needs`, which runs every tick after planning, holds the units, the declared map (`wanted`) and the store, and is where a `Needs:` edge is
already added or pruned. A plan cannot do it: the plan never changes a started unit's dependencies and should not start to. Doing it in `waiting_on`
would hide a stored edge the graph still draws.

Rule: for each unit that is itself neither finished nor in `BUILDS_NOTHING`, every stored `depends_on` entry whose target exists, is in
`BUILDS_NOTHING`, and is not in `wanted[unit.id]` is removed (`store.set_dependencies`), and `<unit>: dropped dependency <parent>: it builds nothing`
is logged. The check against `wanted` is a guard: `wanted` is built from live units only, so a declared line never names a unit that builds nothing
today; it keeps a future change to `declared_needs` from dropping a declared edge silently. A target absent from the store is left (a different fault).

The existing loop starts with `if unit.id not in wanted and not unit.needs: continue`, so a unit with a stale edge and no `Needs:` line would be
skipped; the drop runs as its own pass before that loop, so the rest of the function sees the cleaned `depends_on`. The pass edits a started unit's
dependencies, which the replan requirement forbids a *plan* to do; this is not a plan, and the requirement added here says so. Risk: a dropped planner edge is not restored if a replan revives the parent; an unstarted child gets the plan's edges back, and a started one was admitted
without it, which is accepted.

Dropping changes no wait: `waiting_on`, `base_of` and `depth_of` already ignore a parent that builds nothing. The tick is idempotent: once dropped, the
edge is not found again.

### Any bounce is counted, in the store (d)

Nothing counts a unit that goes `running` then back to `planned` across ticks. These paths of `origin/main` put one back:

| Path | Cause written | Protection against repeating |
|---|---|---|
| `upstream_went_back` guard | `upstream_went_back` | none (the case found) |
| `_step` gated hold, `rebase` second hold (a base that keeps moving) | `base_changed` | none across ticks |
| restack deferred (`build_restack`) | `restack_deferred` | none |
| `reclaim_stranded` (`cli/pipeline.py` ~1709) | `requeued` | none |
| no-thread fallbacks (rework, requeue, release writing `planned`) | `rework`, `requeued`, `released` | none |
| environment waiters (`_resume_environment_waiters`) | `environment` | none |
| host, network and model-service parks | `host_unavailable`, `network_unavailable`, `service_unavailable` | `PARK_BACKOFF`, and `parked_attempts` fails the unit at a cap |

Only the last row has a limit. Stopping a loop automatically is a separate decision with a different answer per path and is not made here; this change
makes every path visible.

**Detection, in one place.** `UnitStore._record_state` appends every state change. On a write into `planned` or `held` from `running` it takes the
run (now minus the `at` of the last `running` history entry). A run of `bounce_span_seconds` or more, or a write with no resolved cause, sets the count to
zero. A shorter run whose cause equals `bounce_cause` raises `bounces` by one; any other cause restarts at one with the new
cause, so alternating causes never reach the limit. `bounce_at` is the time of the last counted write.

Writes into `in_review`, `failed`, `merged`, `closed`, `satisfied`, `unplanned` or `retired` zero it, and so does a person's `abk requeue`: `set_state`
takes the optional `by` that `_record_state` already has and `cmd_requeue` passes `by="abk requeue"`; the automatic requeues (`reclaim_stranded`, gate
cleared, environment waiters) pass nothing and do not reset. Any other write, such as into `running` or a release, leaves the count.

**Fields.** `StoredUnit` gains `bounces: int = 0`, `bounce_cause: Cause | None = None` and `bounce_at: datetime | None = None`, after the `check_reruns`
pattern: optional, omitted from the stored file when empty or zero, carried from `existing` by `upsert` beside the other runtime fields (so a replan
keeps them). The unbuilt change `a-standing-cause-survives-replans-and-no-cause-changes` also adds runtime fields to the same `upsert` call; a rebase resolves it. Nothing is written from inside a guard.

**Parks.** A park is a deliberate wait, but it counts by the same rule as any bounce: the run before it was shorter than `bounce_span_seconds`,
whatever the gap before that run. A park after a backoff wait counts when the resumed run again ends within the span; one whose run did real work (the span
or longer) does not. Three quick `host_unavailable` parks are therefore named looping, which says the outage is not clearing; `parked_attempts` still fails
the unit at its own cap, which zeroes the count. The backoff is unchanged.

**Settings.** `LimitsConfig` (the class behind `global_limits`, `config.py` ~538) gains `bounce_limit: Annotated[int, Field(ge=2)] = 3` and
`bounce_span_seconds: Annotated[int, Field(ge=1)] = 120`, commented like their neighbours (`checks_register_seconds`), under the strict schema; `abk config
--show` prints them and `abk doctor` loads them. `UnitStore` takes the span as a constructor argument beside `on_state`; callers pass the setting.

**What the notice does.** None of it changes scheduling.

- The tick's `on_state` hook (`cli/pipeline.py` ~393) logs one line when the write that just happened brought `bounces` to exactly `bounce_limit`:
  `<unit> is looping: put back to planned <n> times in <span>s by <cause>; last note: <note>` (`held` for a hold). Equal, not at-or-above, so it logs
  once.
- `abk status` prints `  looping: <unit> (<label>) <n> times in a row, cause <cause> — <note>` for a `planned` unit with `bounces >= bounce_limit`,
  and none otherwise.
- `_ready_queue_lines` appends `(looping)` to the marker of such a unit.
- The guard's wording: `upstream_incomplete` ends its note `held repeatedly by <parent>` when the stored `bounce_cause` is `upstream_went_back` and
  `bounces + 1 >= bounce_limit` (the optional `bounce_limit` argument of `build_upstream_incomplete`; unset leaves the note alone). It reads the store and
  writes nothing; the run-length test is made at the write, so the note can name a hold the store then declines to count. A third element in the guard's
  tuple was rejected: it widens the type `base_moved` shares.

## Tests

Wiring tests sit beside `tests/pipeline/test_wiring_acceptance_upstream.py` (built on `tests.factories.stored_unit` and a `UnitStore` in a temporary
directory), the guard's basic cases beside `test_a_parent_that_went_back_is_reported_with_the_upstream_cause` in `tests/cli/test_tick_scheduling.py`, the
drop in `tests/cli/test_link_needs_*.py`, and the counter in `tests/pipeline/test_unit_store_bounces.py`. New files are named in `tasks.md`.
