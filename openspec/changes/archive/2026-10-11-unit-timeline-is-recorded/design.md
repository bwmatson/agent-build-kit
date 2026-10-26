# Design

Every file and function below was checked against `agent-build-kit` as it stands; where the earlier
sketch of this change was wrong, the correction is stated in "Corrections".

## Wait reasons

`WaitReason` is a `StrEnum` in `pipeline/vocabulary.py`, beside the other closed sets (`Cause`, `HeldBy`,
`ReworkKind` are in `unit_store.py`; the display vocabulary is in `vocabulary.py`):

| member | value | the unit is not running because |
|---|---|---|
| `BLOCKED` | `blocked` | work it needs is not done: a prerequisite, a predecessor reworking, a merge-before |
| `QUEUE_FULL` | `queue_full` | `max_units_in_progress` is reached and it has never started |
| `SLOT` | `slot` | it could build but all `max_concurrent_stacks` slots are taken |
| `USAGE_PAUSE` | `usage_pause` | the usage guard paused the pipeline |
| `LEASE` | `lease` | a person holds its chat lease |
| `BACKOFF` | `backoff` | parked for the host being unavailable, backoff not over |
| `WAITING_REVIEW` | `waiting_review` | in review, nothing for the pipeline to do |
| `NEEDS_PERSON` | `needs_person` | held or failed and a person must act |
| `READY` | `ready` | startable now (the instant between becoming ready and being started) |

`SLOT` and `USAGE_PAUSE` keep the strings the ledger already holds in the `waited` field (`spans.SLOT`,
`spans.USAGE_PAUSE`), which become these members, so recorded history and the `abk.wait.duration`
`bucket` attribute do not change. The sketch's name `concurrency` is therefore not used.

`_evaluate` (`cli/pipeline.py`) already decides, per planned unit, which ones are shown to `ready_units`
as `HELD`: started this pass, left out by `--only`, a lease, a gated requeue, a backoff. That decision
moves into one function returning `(view, reasons)`; `ready_units` and the stored state decide the rest
(`waiting_on` for `BLOCKED`, `start_room` for `QUEUE_FULL`). `run_round` calls it once per round, so
`_evaluate`'s result is unchanged and the reasons are the same facts it already used.

## The decision log

`WaitRecorder` keeps the last `(reason, waits_on)` per unit, loaded from the tail of
`<state_dir>/decisions.jsonl` when it starts, and appends `{at, unit, reason, waits_on, tick}` only when
the pair changes. A unit that is running, merged or closed gets a final record with reason `none` so the
log shows when each wait ended. Ten thousand ticks of "still blocked" write nothing. A write that fails
is told once and never fails a pass, as for the usage ledger.

## Unit record

`StoredUnit` (`pipeline/unit_store.py`) gains `ready_at: datetime | None = None` and
`first_human_activity_at: datetime | None = None`.

- Start and review entry are **not** new fields: `history` already stamps every state change
  (`{"state", "at"}`), `_review_waits` in `usage_report.py` already derives review stretches from it, and
  a second copy would disagree. Two accessor properties read them.
- `ready_at` is set once, the first time the unit is evaluated with nothing blocking it (concurrency cap
  lifted, as `note_queued` in `_schedule` already evaluates). That mark lives only in memory for the
  pass today and is lost at restart, hence the stored field. It is not reset by a later rework. **How best
  to derive it for units that were ready before this change is unverified**; those read as absent.
- `first_human_activity_at` is set by the first poll that finds a conversation id on the unit's pull
  request that is not in `pr_replies.own_posts` (the pipeline's own posts; `pr_poller._comment_ids`
  already takes that set as `ignore`). The forge model gives `conversation` as ids only (no author, no
  time), so the value is the time of the poll that saw it, at most one poll interval late.

### Unit-store resilience

The store is committed and read by whichever release runs. The rule for these fields, which any new
`StoredUnit` field follows: the default is the empty value (`None`) so a unit without it reads as it did;
the field is **omitted from the written record while it holds its default** (the store writes
`model_dump` in full today, so this change excludes these two fields when unset), which keeps diffs of
`units.json` quiet; an older release drops an unknown key that is empty and **refuses a record holding an
unknown key with a value** (`_tolerate_other_releases`), naming the unit, the field and the value; and
the changelog says that a store written after these fields are set needs this release.

## Spans

The existing `Span` (`pipeline/spans.py`) already has `waited` (the bucket of a wait; empty for work),
`node`, `outcome`. No `waiting` node is added: a wait is a span with `waited=<WaitReason>` and no node,
as `slot` and `usage_pause` are today (`usage_report._span_row` and `export_span` already sum by
`waited`, and a second representation would count a wait twice). New: waits for `queue_full`, `lease`,
`backoff` and `needs_person` are recorded when they end; a unit parked on a pause between nodes records
`usage_pause` (it does, in `graph/nodes.py`); a review round is a span with a `cause` of `review`,
`check` or `conflict` (conflict = the rework or adapt a restack started, which gives rebase cost per
unit). `cause` is a new optional field on `Span`; readers ignore unknown fields. `effective_state` in
`vocabulary.py` shows a usage-paused unit as `paused`, derived beside `rebasing`, with no stored state.

## Samples

Each `_schedule` wake-up (a completion or `REFRESH_SECONDS` = 300 s) appends one ledger row
`{kind: "sample", at, running, in_review, blocked, queued, free_workers, limit, cap}`. The reader
(`usage_report._entries_in`) skips kinds it does not know, so older readers are unaffected. The gauges
`abk.slots.free` and `abk.slots.idle_with_ready` are set with `telemetry.level(name, value, **attributes)`,
beside `abk.units` in `_record_unit_states`; they carry no unit or change attribute. A sample counts an
hour as **idle** when no unit is running; idle with a full queue when `in_progress` units reach the
limit, idle with room otherwise.

## Summaries

The roll-up that writes `summary` lines runs when a change is **archived**, not at merge. It already
sums `slot_wait_ms` from spans; `pause_wait_ms` is null because pause spans were not matched and
`review_wait_ms` because review waits are derived from history at report time. The roll-up now writes all
three for every unit, with review wait split into person, round and checks:

- person: from entering review to `first_human_activity_at`, or all of the stretch when nobody answered;
- round: the time of review-round spans (review, check, conflict causes);
- checks: the remainder of the stretch spent waiting on checks.

## Ledger completeness

`record_call` has one caller (`graph/nodes.py`), so the gap between 244 agent rows and 418 `claude done`
lines is not obviously a missed path; whether it is paths that bypass the node, resumed calls counted
once on purpose, or lines in the log that are not calls is **unverified**. A conformance test runs every
path (new, resumed, continued; Claude and ACP) and asserts one row per call; what it finds is fixed.

## Retention

The per-tick logs in the state directory (24 files here) are **not written by this code**: nothing in
`agent-build-kit` creates `tick-*.log`, so the host's timer wrapper owns them and this change does not
prune them (unverified who does). What the framework writes is bounded: `decisions.jsonl` by size
(`retention.decision_log_mb`, default 50), and unit logs, today the last 3 runs per unit
(`RUNS_KEPT`) and removed at archive, additionally by age (`retention.unit_log_days`, default 30). A
unit's log is summarised into the ledger (`rounds`, `agent_calls`, `outcome`) before it is pruned.

## The report

`abk report --waits [--by unit|day]` reuses `Report`, `ReportRow` and `_time_row` from `usage_report.py`
and adds rows by cause: planned-blocked, planned-ready (slot), running-agent, running-checks,
running-other, in-review-person, in-review-round, paused, failed; plus idle-with-room hours and the
estimate ratio (actual over estimated lines) per kind.

### Worked example fixture

A recorded fixture (a ledger, a decision log and a units file, synthetic but pinned to these totals)
the report must reproduce:

| figure | value |
|---|---|
| merged units | 72 |
| time in `planned` | 1,343 h |
| time in `in_review` | 172 h |
| time in `running` | 93 h |
| agent calls | 11.6 h |
| hours observed | 87 |
| hours the pipeline ran nothing | 47 |
| of which queue full | 17 |
| of which room to spare | 30 |

`running` less agent time leaves about 81 h to account for as checks and other; the fixture pins the
named totals and the 17/30 split, not a breakdown inside `planned` (earlier notes quoted a 17 h mean, 9.3
h on prerequisites, 3.4 h without a slot and a 14 h p90, which do not add up; the report computes its
own).

## Corrections to the earlier sketch

- A `waiting` node span is wrong; waits are `waited` spans with no node.
- `concurrency` is the existing `slot`.
- `started_at` and `review_requested_at` already exist as history entries; only `ready_at` and
  `first_human_activity_at` are new fields.
- `own_posts(root, slug, pr)` returns comment ids, and the poller has no authors or times.
- Summaries are written at archive, not merge; `slot_wait_ms` is already filled, `pause_wait_ms` and
  `review_wait_ms` are not.
- Tick logs are not the framework's to prune. No `retention` config section exists; this adds one.
- The store writes defaults today; "omitted when default" is new behaviour for these fields.
