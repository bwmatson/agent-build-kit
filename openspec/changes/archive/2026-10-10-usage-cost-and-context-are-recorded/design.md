# Design

## What is wrong, with the numbers

Measured on this installation's ledger when this change was written (341 agent rows, all runtime `claude_code`, source
`reported`, 242 sessions, 41 units; no session spans two units; rows are in time order; no step of any session falls):

| Figure | USD |
|---|---|
| Sum of the agent rows' `cost_usd` (what is recorded) | 558.51 |
| Sum of each session's increments (its true spend) | 266.34 |
| Sum of each session's final cumulative | 266.34 (equal, as it must be) |
| Overstatement | 292.17, which is 52.3% of the recorded figure; recorded is 2.10 times the truth |
| What `abk report` shows today (the reader keeps one record per unit, node and round, see below) | 479.14 |
| What the report would show once the rows are increments | 206.38 |
| Summary rows already written at archive (24 of them), `measured.cost_usd` summed | 203.43, overstated by the same mechanism and not recomputable here |

Per unit, recorded against true (sum of the session increments):

| Unit | Rows | Recorded | True |
|---|---|---|---|
| abk-web-ui/8 | 22 | 160.98 | 36.40 |
| ui-review/2 | 22 | 62.54 | 19.17 |
| flaky-tests/2 | 7 | 28.39 | 11.90 |
| ui-chat-editing/1 | 7 | 26.51 | 10.70 |
| process-tests-fake-the-github-api/2 | 16 | 20.00 | 8.73 |
| local-forge/2 | 15 | 20.00 | 10.86 |

(The earlier planning figures, $530 against $253 over 325 rows and 231 sessions, were a snapshot of the same ledger
before later runs appended to it; the ratio is the same. The builder reproduces the table above from the ledger as it
then stands, not these digits: the ledger grows.)

The mechanism, on one session (`fa6a7585`, unit abk-web-ui/8, nine calls). Recorded cumulative against the call's own
spend:

| Call | Recorded | Own spend |
|---|---|---|
| tests 0 | 2.63 | 2.63 |
| implement 0 | 5.49 | 2.86 |
| rework 1 | 13.18 | 7.69 |
| rework 2 | 15.40 | 2.22 |
| rework 0 | 19.77 | 4.38 |
| fix_checks 1 | 20.62 | 0.84 |
| rework 1 | 21.40 | 0.78 |
| rework 0 | 23.92 | 2.52 |
| rework 1 | 25.39 | 1.47 |

Own spends sum to 25.39, the final cumulative; the recorded column sums to 147.80. Token counts in the same rows are
per call (cache-read goes 6.9M, 10.4M, 30.7M, 9.5M, 2.4M, 1.0M), so only cost is cumulative.

All 99 resumed rows follow a row of their session; no non-resumed row is anything but the first of its session. Every
session's recorded cost is non-decreasing (0 falls in 341 rows), which is the evidence that the stored figure is a running
total and not a per-call spend.

### Where the code does it

- `runtimes/claude_code.py` `_spent` returns `"cost_usd": ended.total_cost_usd`, the `result` event's total.
  `pipeline/claude_stream.py` `ResultEvent.total_cost_usd` carries it. Nothing subtracts a baseline.
- `runtimes/acp.py` does subtract one, but the baseline is not a durable record: a `_Session` is built per call, a
  resumed call moves `session.cost_usd` to `session.cost_baseline` after the session is opened, and `_spent` gives a
  resumed call without a baseline no cost at all. So ACP's figure is right when the agent replays its `usage_update`
  while loading the session and absent otherwise. (UNVERIFIED here: whether the agents in use replay it.)
- `graph/nodes.py` `_recorder` builds the `UsageRecord`: `cost_usd=spent.cost_usd if exact else result.cost_usd`,
  and, with a gateway, `reported_cost_usd=result.cost_usd`. For a Claude Code call that is the running total, so the
  gateway-versus-reported difference in the report is also wrong for a resumed call.
- `pipeline/usage_ledger.py` `records_in` keeps one record per unit, node and round, and adds a resumed call's figures to
  the record it resumed (`_combine` sums `cost_usd`). `export_call` adds `cost_usd` to `abk.agent.cost`.
- `pipeline/usage_report.py` sums `cost_usd` in `Figures`, and `roll_up_change` writes the summary rows from those sums.
  `serve/metrics.py` (`MEASURES["abk.agent.cost"]`) reads `cost_usd` from the ledger's records.
- `graph/state.py` `AgentSession` holds `session_id`, `runtime`, `model`, `node`, `round` and `head`: no cost.

### A second effect the reader's rule hides

`records_in` replaces a record when a non-resumed one arrives with the same unit, node and round (a re-run). On this
ledger that rule removes $60 of real spend from the report (the $206.38 above is $59.96 short of the $266.34 true
total): for example abk-web-ui/8 has several `review` calls at round 1 in different sessions, and the report keeps one.
Whether those are re-runs or genuine repeat calls is not established here. This change does not alter that rule; the
report's cross-check (below) puts the ledger's session total beside the report's total so the gap is visible. Deciding
whether the key needs the call's own id is an open question, not a task.

## Design

### Group 1: both costs on every row, and the sums become right

One `cost` object on every agent row; the flat `cost_usd` and `reported_cost_usd` fields go away.

| Field | Meaning |
|---|---|
| `incremental_usd` | this call's own spend; null when it cannot be known |
| `cumulative_usd` | the session's running total as the runtime reported it, or for runtimes that report per call, the running sum of the session's rows |
| `basis` | a `CostBasis` StrEnum, below |
| `reported_usd` | the runtime's own incremental figure where a gateway's is recorded instead (replaces `reported_cost_usd`) |

`CostBasis` is a `StrEnum` (closed set, never bare strings):

| Member | Meaning |
|---|---|
| `reported` | the runtime gave the call's own figure |
| `derived` | the difference of two cumulative figures |
| `first` | the session's first call, baseline 0 |
| `unknown` | a resumed call with no known baseline |
| `backfilled` | written by the backfill command |
| `legacy` | an old row with a flat figure not yet backfilled; read-only, never written |
| `cumulative_summed` | an archived summary whose figure was summed from cumulative rows and could not be recomputed; summaries only |

Every sum (unit, change, repository, day, report, summaries, the web UI's usage view) and the `abk.agent.cost` counter
read `incremental_usd`. The report's own `cost_usd` column names and the summary rows' `measured.cost_usd` keep their
names and now carry the incremental sum, so an older summary and a JSON consumer still load.

Reading old rows: a line with a flat `cost_usd` and no `cost` object is read as `cost = {basis: legacy,
incremental_usd: null, cumulative_usd: null, legacy_usd: <the old value>}`. A legacy figure is never added to an
incremental one. The report counts legacy rows, lists them, and shows their legacy total on a separate line until the
backfill is run. A line with the object ignores the flat fields. An older reader of a new ledger sees no flat cost; that
is intended, since it cannot then mis-sum it. The `usage-reporting` tolerance rules for older summaries stay true.

**Claude Code runtime.** `_spent` reports the result's `total_cost_usd` as `cumulative_usd`. `incremental_usd` is that
minus the session's previous cumulative; the baseline of a new session is 0 (`basis: first`), otherwise `derived`.
The previous cumulative is a field on the recorded `AgentSession` in graph state, written when the call ends (the
`_ended` tuple the recorder sets carries it to `_sessions_after`, and to `ported_session`), and cleared with the session.
A resume with no recorded baseline falls back to the last ledger row with the same session id (the ledger is the durable
record). When neither exists the row is `basis: unknown` with `incremental_usd` null, never the total. A cumulative
figure lower than the baseline is a reset: it is treated as a new session, recorded with its own figure as incremental and
the reset noted in the log. A call cut off by a usage limit still reports the spend so far, so its cumulative becomes the
baseline of the call that resumes it.

**ACP runtime.** Already incremental when a baseline exists. It additionally records `cumulative_usd` (the update's
amount) and `basis` `derived` or `first`, and takes the same recorded-baseline fallback so a resumed call whose agent
did not replay its update is not left without cost.

**Gateway-attributed runs.** The gateway's totals are per call (one key per run); `incremental_usd` is that figure,
`basis: reported`, `cumulative_usd` the running sum of the session's rows, and `reported_usd` the runtime's own
incremental figure (derived from its cumulative as above), so the report's difference compares like with like.

**Reader.** `records_in` still keeps one record per unit, node and round and adds a resumed call's figures to the record
it resumed; with incremental figures that adds only spend. A test pins that a session of N calls sums to its final
cumulative. A cumulative figure of a combined record is the last part's.

**Report.** Unit and change totals, summaries and telemetry are right from here on. The report gains a per-session
`cumulative` column (final cumulative) as a cross-check and flags a session whose increments do not sum to its final
cumulative.

**Resilience.** The `cost` and `context` objects are optional on read, and a figure that is the wrong type reads as
absent, as the usage figures do today.

### Group 2: the temporary backfill

`abk usage backfill-costs [--apply]`, a `usage` subcommand beside `report`; a dry run unless `--apply`.

For each agent row without a `cost` object (`legacy`), group by `session_id` and order by `at`:

- `claude_code` rows with source `reported`: the stored flat figure is the cumulative. Set `cumulative_usd` to it,
  `incremental_usd` to the difference from the previous row of that session (the first row: itself), `basis:
  backfilled`, and remove the flat fields.
- ACP and gateway rows are already incremental: `incremental_usd` is the stored figure, `cumulative_usd` the running sum
  of the session's rows, `basis: backfilled`.
- A session in which a figure falls is left `basis: unknown` with `incremental_usd` null and is listed.

Safe: it writes a timestamped copy of the ledger first, takes the ledger lock (`pipeline/file_lock.py`; appends and the
archive roll-up take it, `usage_ledger.ledger_lock`), rewrites through a scratch file and `os.replace`, is idempotent
(a row with a `cost` object is skipped), and prints before and after totals per unit and overall plus the number of rows
changed and left unknown. For the ledger above the expected output is: 341 rows changed, 0 unknown, overall 558.51 to
266.34, and the per-unit table above. `--apply` is required to write.

**Summaries of archived changes** were computed from overstated rows and their detail rows were rolled up. If a unit's
detail rows still exist the command recomputes its summary through `roll_up_change`. If they do not, the summary cannot
be recomputed: the command sets its cost `basis: cumulative_summed` (still overstated) and lists it. Here the 24 summaries
carry $203.43.

**UNVERIFIED: whether archived detail survives anywhere.** The ledger's detail rows of archived changes were replaced
by the roll-up; the retained transcripts (170 files) record per-call result aggregates but carry no cost, and no archive
folder of ledger lines was found under the state directory. Whether a backup, a git history of the state directory or an
export holds them is not known. The command treats absence as the normal case.

**Telemetry.** The exported counters cannot be corrected. `abk.agent.cost` is right from the release that ships group 1;
dashboards built on it before overstate, and the documentation says so rather than rewriting history.

**The command is temporary.** It exists to repair a ledger once. Its help text and documentation say "temporary: removed
once every installation has run it". Removal is a recorded TODO in `follow-ups.md`, not a task group: a group would be
planned and built at once, before anyone has run the command. The legacy-row reader tolerance stays when it is removed.

### Group 3: context window used against max

Every agent row gets one `context` object, in tokens (a percent is only a display):

| Field | Meaning |
|---|---|
| `used_end` | tokens in the context at the step's last request (input + cache read + cache creation of that request): the cumulative fill |
| `used_start` | the fill at the first request: what the step inherited from the session |
| `added` | `used_end - used_start`, the step's incremental growth, never negative (a step that shrank records 0 and a compaction) |
| `peak` | the largest fill at any request in the step |
| `compactions` | how many times the step compacted, 0 for most |
| `max` | the model's window size in tokens |
| `basis` | a `ContextBasis` StrEnum: `reported`, `estimated`, `unknown` |

`peak` equals `used_end` unless the context shrank during the step, so its value is how close a step came to the limit
even when it ended lower. A step starts at 150k of 200k, reads files up to 195k, the agent compacts and it ends at 80k:
the end fill says safe and `added` is 0, while the peak of 195k of 200k says it nearly lost context and a fresh session
or a smaller step is the fix. It is stored (one number) and the report shows it only where it differs from the end fill.

`compactions` is counted from the runtime's own marker where it has one, and otherwise from a drop in the fill between
consecutive requests larger than `context.compaction_drop_share` of the window (default 0.3). For ACP it is counted from
a drop in `used` between updates.

**Claude Code runtime.** Per-request usage comes from each `assistant` stream event's message usage. Correction to the
earlier plan: `pipeline/claude_stream.py` does not read it today; `records()` takes a `usage` figure only from the
`result` event, so the transcript's single `usage` event per call is the run's aggregate (for the session above one call
shows 5.7M cache-read tokens, far beyond any window). Per-request tracking is new code: an event that repeats a message
(one per content block) counts once, and requests made by a sub-agent are not the main context. `max` comes from the
result's `modelUsage[model].contextWindow`, added to `ResultEvent` as a salvaged field, with a per-model table in
configuration (`runtimes.context_windows`, no default beyond the models the configuration names) when the event omits it.

**ACP runtime.** `UsageUpdate` has `used` ("tokens currently in context"), `size` ("total context window size") and
`cost` (verified on the pinned schema); the runtime reads only `cost` today. `used_end` is the last update's `used`,
`max` its `size`; `used_start` is the previous step's end for a resumed session and the first update's `used` for a new
one.

**UNVERIFIED, to confirm against a recorded stream in the first test of the group:**

- whether Claude Code's stream carries a compaction-boundary system event, and its name and shape; until confirmed the
  drop-share rule is the only counter for that runtime;
- whether the models used here report `modelUsage[model].contextWindow` on the result (the table covers the case);
- whether `assistant` events' usage is per request and how sub-agent events are marked.

**Reports and display.** `abk report --context` shows, per step kind, the mean and p90 of `added`, the compaction count
and the end fill as `used / max` (for example `142k / 200k`), per session the growth across its steps, and the steps that
add the most. Telemetry gains the gauges `abk.agent.context_used` and `abk.agent.context_max` per call and the counter
`abk.agent.compactions`. A warning is logged when a step ends above `context.warn_share` of the window (default 0.8): a
signal only, and no scheduling decision uses it in this change. Tokens rather than percent because two windows make a
percent ambiguous; with the max beside them a percent can be derived anywhere.

**Missing figures** give `basis: unknown` and absent fields, never zero, and never fail a run.

**No backfill of context.** Correction to the earlier plan, which offered a `--context` option on the backfill filling
rows from retained transcripts: the transcripts hold only each call's aggregate `usage`, not per-request usage, so start,
end, peak and compactions cannot be rebuilt from them. Existing rows keep no `context` object and read as `unknown`.
What cannot be recovered: context figures for every row written before group 3, cost for archived summaries without
detail, and the counters already exported.

## Why no MODIFIED requirements

The existing requirements say a call's cost is recorded and a resumed call is counted once; none says the cost's meaning.
Every new rule is an addition that those requirements do not contradict, so the deltas are ADDED only and no original
scenario is restated. The reader's key rule (one record per unit, node and round) is unchanged.
