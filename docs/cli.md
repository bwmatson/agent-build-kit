# The `abk` command line

`abk [--config PATH] <command> ...`. `--version` prints the framework version.

Most commands need an **installation**: an `abk.yaml` found through
`--config`, `ABK_CONFIG` or the nearest one above the working directory
(see [configuration.md](configuration.md)). When none is found they print
`abk: no abk.yaml found ...` and exit 2. Commands marked *optional* run
without one; `init` and `doctor` never load one the usual way.

| Command | Installation |
|---|---|
| `tick`, `status`, `graph`, `verify`, `tags`, `check`, `archive`, `openspec`, `config`, `scrub-check`, `track` | required |
| `gate`, `install-skills` | optional |
| `init`, `doctor` | not loaded (doctor loads and checks it itself) |

A second console script, `abk-policy-hook`, is the PreToolUse hook entry
point; the pipeline registers it per run as
`<interpreter> -m agent_build_kit.hooks.policy`, so nothing calls it by hand.

## Pipeline

### `abk tick [--dry-run] [--only UNIT ...]`

One pass of the loop, the command the timer runs every few minutes. With
`ABK_USAGE_GUARD=off` its first line is `usage guard off (ABK_USAGE_GUARD) — no usage is read
and no start is held for usage`, and `abk status` shows the same line. In
order: exit silently if nothing needs a tick (no unit `planned`/`running`/
`in_review` and every change planned in its current form); stop if paused;
read the usage windows and pause if either is past the threshold that applies
to it now (`usage_pause_pct` in the `session` / `weekly` section of
`runtimes.claude_code.limits`, rising towards its `usage_pause_ceiling_pct` as that
window's reset nears, when one is set) or unknown; `git fetch --prune origin` in every repo; poll each repo's host; plan changes whose `tasks.md` changed; apply
`Needs:` lines; verify and archive fully merged changes; then resume the units a killed
run or a usage pause left `running` from their threads and build the ready
units, up to `project_limits.max_concurrent_stacks` at once in each project. No unit that has never
started does while the units in progress in its project are at
`project_limits.max_units_in_progress`, and a pass starts no more than fit under it;
the tick log and `abk status` then say "queue is full: N units in progress,
limit M" followed by the count in each state, and, while the project's emergency lane
(`project_limits.emergency_extra`) has room, that a priority-0 unit may still start; a unit in
the lane is shown as `emergency room N/M used by <unit>`. There is one such line for each project at its
limit, and a workspace with several projects names the project in it
(`queue is full: app/web: 9 units in progress, limit 9 (...)`); each line lists only its own
project's blocked and failed-waiting units, and the reason a pass started nothing names only
the full projects that hold a ready unit back. A unit of a repo with several projects is
labelled `(repo/project)` wherever a status line names it. A workspace with one project reads
as it always did. Free slots
go to open-PR work first (reworks, restacks), then resuming builds, then new
units.

The pass keeps building until nothing is in flight and nothing is ready. Every
build that finishes is followed by another fetch, another poll and a fresh
readiness check, so what it unblocked — a child whose parent is now in
review, a dependent whose dependency merged — starts in the same pass. A pass
can therefore run for hours. Every refresh of a pass runs the same round as the
tick: the usage check, fetch and poll, planning, reclaim, verification and
archive, then readiness. Verification is skipped for that round while the live
stack is in use. A poll event for a unit whose build is still running is left
for a later poll rather than acted on mid-build. A unit the pass built that a
review sends back, that its own build held because its base moved, or whose thread a
comment resumes, is started again in the same pass, at most twice; a unit stopped for
any other cause waits for the next pass. A refresh whose usage guard refuses
starts nothing and skips planning, but still fetches, polls and archives (below).

- `--dry-run` runs everything up to the build and reports what is ready
  without building. For each recorded pre-existing e2e-test failure it also prints
  `exists: <change>` (the open fix change) or `would write: <change>` (a change, or the
  successor of an archived one), even when no unit is pending; it writes nothing and runs
  no base run.
- `--only UNIT` (repeatable) builds only those units if ready, at every
  readiness check of the pass; polling, planning and archiving still happen.
  For pushing one unit through when usage is tight.

A build the usage guard refuses pauses only that unit: the pass goes on with
its rounds, recording merges and comments, asks the guard again at each one,
admits builds as soon as it allows and resumes the paused units. A window
that is used up refuses every start each round. A build the model itself
refuses (rate limited) stops new builds from starting until its pause ends;
builds already in flight are still awaited before the pass ends. Rounds run
only while a build is in flight, so a pass resumes paused units only while
other builds keep it running; otherwise the next tick does.

Exit 0, including when paused or idle. A tick is idle unless a unit is
planned, running or in review, a change's tasks are unplanned, or a change with
a satisfied unit is ready to archive and not yet verified (a failed
verification is kept, so it does not keep ticks busy). Exit 1 when a repo about to be built
has no repo-local `user.email` (agent commits would fall back to the machine's
global identity) — which can come mid-pass, after other units have already
been built, since each readiness check can reach a new repo. A unit that fails
is recorded `failed`, not an exit status.

A tick that starts nothing, and is not held by a usage pause, a deadlock, a full queue or
a failed unit that others wait on (each of which prints its own report), prints `nothing ready to build` and then one line for each planned, held or failed
unit: `  <unit> (<repo>): <reason>`, with `, waits on <units>` when it waits on others. The
reasons are those `abk status` and the decision log give. Units a person can act on
soonest (`ready`, `slot`, `lease`, `backoff`) come first; at most 10 are shown, then
`  (+M more)`. If the reasons cannot be worked out, one line names the error.

### `abk status`

Prints whether the pipeline is paused (until when, why), the usage reading held
(session %, weekly %, source and age; no call is made, and `--refresh` asks the endpoint for a
fresh one, no more often than the cache time allows), the count of units by state, and each
`in_review` unit with its PR. A unit whose pull request conflicts reads `conflicts with <base> since <time>; moved N times` and what it waits for (the next poll, the end of a build of its branch, or the end of a usage pause); a held one adds the hold's reason and that a person is needed. A `no recorded cause:` line lists the units that are `held`
or `planned` with work on them and no cause on their last history entry. A repository with a
`tests.replay` section adds a `cassettes:` line with the count of recordings waiting for review.
A `flake storm:` line shows each run that failed more than `global_limits.max_flakes_per_run` tests on its
first pass that all passed alone, as one line with its count and no per-test entries; its record
keeps the first three failures' own sections of the run's output (up to 3000 characters each, from
the end), and so does the log. Each flaky test's record keeps, next to `output`, `failure`: its
own section of the first run's output with the traceback, up to 6000 characters from the end, empty
when the profile reads none. At each
planning pass a planned unit that never started, whose change directory no longer exists, becomes
`unplanned`, and a unit waiting on it stops waiting. A `flaky:` line lists each flaky test with
its count and fix change, and a `pre-existing:`
line each test that failed e2e-test on the base too, with how many times and its fix change.
An `e2e-test:` line names the unit holding the e2e-test lock and for how long; a record left by a
process that is gone, on a free lock, is shown as stale, a held lock whose recorded process is gone
says so, and a free lock with no record prints nothing.
A split with a `gate` adds a `gate usage:` line: the split, the provider, the amount used against the budget and as a percent, the threshold now (and what it moves towards while it ramps), when the window resets, whether the split is held or usable or its usage unknown (with the reason), and the source and age of the reading. A command gate shows its result and reason. A split held by another source shows that source as the hold. Without `--refresh` only the cache is read, so no provider is asked and no command is run; `--refresh` reads afresh.
The `queue is full` lines are one for each project at its limit, as the tick paragraph above says.
A `restacks: N running, M waiting` line, which totals the lane of every project, printed only while a restack lane has work or a unit
is owed a restack, is followed by each unit as `restacking onto <base>`; a restack waiting for a
usage pause is listed with the pause. The lane runs the whole moved-base run of a unit whose base moved, so a unit
shows as `restacking onto <base>` for the whole run, not only the move; the lane's cap bounds the moved-base run, and a
run the lane cannot go on with is handed back to a build worker, `planned` with the cause `restack_handed_back`. The
slots line shows that the run counts toward slot occupancy, so it may read over the cap, as in `slots: 5/4, 1 restacking` (the line totals every project, like the restacks line, and its cap is the per-project cap times the projects with unfinished work): the run is
never held back by the limit on build workers, but no build starts at or above it. A record left by a tick that has gone
is ignored.
Changes nothing. Exit 0.

### `abk replay review [--keep NAME ...] [--delete NAME ...]`

Lists, for each repository with a `tests.replay` section, the recorded calls held for review: a
recording no passing run asked for, or one a live call at the same test and call index
superseded. Each is shown with the reason, its request, the request that replaced it and where
the two differ. `--keep NAME` clears the mark and leaves the file; `--delete NAME` removes it. A
kept recording is marked again when a later passing run does not ask for it, or a live call
supersedes it. NAME is as the listing prints it. Exit 1 when a NAME matches nothing waiting, or no repository has a `tests.replay` section and a NAME was given; else 0.

### `abk graph`

Rewrites `planning.graph_page` from `runs/units.json`. The tick does this on
every store write; this is for a page that went missing. Exit 0.

### `abk report [--by GROUPING] [--since DATE] [--change CHANGE] [--unit UNIT] [--include-estimates] [--json] [--context]`

Tokens by kind, cost and time by bucket (agent, checks, slot wait, usage-pause wait,
review wait) from the usage ledger and the unit store, grouped `--by` unit (default),
change, node, role, model, repo or day. `--since` (a date) keeps calls on or after it;
`--change` and `--unit` narrow to one. Estimated figures sit in their own columns and
stay out of the totals unless `--include-estimates`; a figure never recorded prints as
`-`, never `0`. The source column says whether figures were `reported`, from the
`gateway`, `estimated` or `none`, and flags a row whose gateway and agent-reported
figures differ by more than 10%. `--json` prints the same rows, with the difference.
Calls made with no unit (planning, track runs, init, the login refresh, and
chat on a session attached to no unit) are listed by node under `pipeline overhead` in the
by-unit view, and in the JSON as `overhead`. A chat turn on a unit's session is shown on its
unit.
Cost is the sum of each call's own spend. Under the table, each session shows the sum of its
increments beside its final `cumulative` figure and is flagged when they differ; rows written
before costs were recorded per call are counted and listed as `legacy` with their total on a
line of their own, never in the cost, and calls with an unknown cost are counted.
A change archived by the pipeline is read from its per-unit summary, so its totals do
not change, and its summary keeps a breakdown by node, role, model and source, so
`--by node`, `--by role` and `--by model` split it as before it was archived. A summary
written before breakdowns existed reads as one row, `(archived, no breakdown)`. Archived
figures are dated by the unit's last call, so `--by day` and `--since` place them all on
that day. Exit 0.

The same figures are written to `planning.usage_page` on every store write.

`abk report --waits [--by unit|day] [--json]` reports wall time instead of cost. Each unit's
time from its state history is split into planned-blocked (before its ready stamp, the
unit's `ready_at` or else the first decision that said it could start), planned-ready
(waiting for a slot), running in the agent, in checks and in other work, in review for a
person or in review rounds, paused and failed; the causes sum to the wall time, and one
never recorded prints as `-`. The `planned`, `in review` and `running` figures under the
table, and in the JSON total, are the time in those states from the history, whatever the
causes divide it into. A planned stretch of a unit with no ready stamp is not divided into
blocked and ready, since that was never recorded; its rounds are still counted.

A review round is a rework, check-fix or adapt round that began after the unit first entered
review. It runs while the unit is running or planned, so its time comes out of that stretch
and counts as in-review-round, and a round before the first review is running time. A
round's own agent and check time are also counted under their causes, so those overlap the
round. The time in review is a person's up to `first_human_activity_at` (all of it when
nobody answered), and what is left of it, the checks', is counted under running-in-checks.

Under the table: the hours of the ledger's samples in which nothing ran, split into a full
queue (running plus in-review units reaching the limit; failed units and ones holding a
branch also fill it, but a sample does not carry them, so those hours read as room to
spare) and room to spare, and the estimate ratio (actual over estimated lines) per kind of
merged unit. At archive each unit's summary carries `slot_wait_ms`, `pause_wait_ms` and
`review_wait_ms`, the last split into `review_person_ms` and `review_checks_ms`, which sum
to it. `review_round_ms` is recorded beside them, not as a part of it: the rounds lie
outside the review stretch. The person's figure is the one the report shows. Exit 0, or 2
for a grouping other than `unit` or `day`.

`abk report --context` prints the context window's use instead of cost: per step kind the mean
and 90th percentile of what a call added, the compactions and the end fill as `used / max`
(the peak only where it differs); per session the fill after each step; the steps that added
the most; and the number of calls with no context figures, which stay out of the means. Rows
written before context was recorded have none.

### `abk usage replay [--since TIMESTAMP] [--session-allowance N] [--weekly-allowance N] [--margin N]`

Re-runs the usage estimate over the recorded readings and the ledger. Read-only: no model
call, no call to the usage endpoint, nothing written. For each window and each usable gap
(the pairs calibration uses) it prints a row, `<window> at=<time> before=<n> after=<n>
units=<n> allowance=<n> estimate=<n> diff=<n>` (`diff` is actual minus estimate), then per
window the counts of underestimates (actual above the estimate), misses beyond the margin,
false pauses (the estimate plus the margin is not under the threshold while the actual
reading was) and false allows (the reverse), and the mean overshoot: estimate minus actual,
averaged over the gaps where the estimate was above (`none` when no gap overshot), the cost of
caution. A window with fewer usable gaps than `usage_allowance_min_pairs` says there is not
enough to judge. The output ends with the `usage allowances:` line the settings give today.
The estimate and the refusal rule are the guard's own.

- The allowance of each gap is the one calibration would have given from the gaps before it
  (the configured one while there were fewer than `usage_allowance_min_pairs`).
  `--session-allowance` and `--weekly-allowance` fix one; `--margin` replaces
  `usage_headroom_margin_pct`.
- `--since` (an ISO time) keeps the gaps whose first reading is at or after it; a malformed
  value is refused.
- The threshold is the window's configured `usage_pause_pct`, and the output says so: the
  record keeps no reset times, so a threshold moving towards a reset is not modelled.
- With no usable gap it prints `no usable gap` and exits 0.

### `abk redact-history [--apply]`

**Temporary: removed once every installation with stored history has run it and a second
dry run finds nothing.** Redacts what was saved before known secret values were redacted on
the way in: `units.json`, the run logs, the transcripts and the usage ledger in the state
directory. It builds the same set of known values the pipeline does. A dry run (the default)
prints, per file, the names found, never a value, and writes nothing. `--apply` replaces
the values and keeps the original beside each changed file as `<file>.pre-redact`, for the
operator to delete (they hold the original values, so the planning repo's `.gitignore`
ignores them and `--apply` says so again). A second run reports nothing. `--apply` refuses,
with exit 1 and nothing changed, unless a pause is in force: a run log or transcript an
agent is writing cannot be locked against, so pause the pipeline first. `units.json` and the
ledger are rewritten under the lock their writers take, written aside and renamed into
place. Earlier versions of `units.json` in the planning repo's git history still hold the
values and are not rewritten. A value containing a quote, backslash or non-ASCII character
is stored escaped in the JSON files and is not found there. It calls no code host: pull request
descriptions and comments already posted are the operator's to edit by hand. Exit 0.

### `abk serve [--port PORT]`

Serves the pipeline's state over HTTP on the loopback address only (`127.0.0.1`, port
8765 unless `--port`), until interrupted. Apart from the unit actions below, the API is
read-only: it answers from the unit store, the usage ledger, the run logs and the
checkpoint database, and changes none of them. A unit is addressed as `change/N`.

| Path | Answers |
|---|---|
| `/api/pipeline` | every unit with its effective state, cause, holder and note |
| `/api/units/<change>/<n>` | one unit: state, cause, note, history, base, branch, pull request, dependencies with their states, the review round from its thread, and `actions`: each of requeue, hold, release and approve with `name`, `enabled` and the `reason` it is not |
| `POST /api/units/<change>/<n>/actions/<action>` | runs `requeue`, `hold`, `release` or `approve` (see below): 200 with a `message`, 409 with the refusal as `detail`, 404 for an unknown unit or action |
| `/api/units/<change>/<n>/logs` | the unit's runs: name, step, start (UTC) and whether each is live |
| `/api/units/<change>/<n>/logs/<name>?offset=<bytes>` | the run's lines after the offset with their clock in UTC, the offset to ask from next, `live`, and the `outcome` once it has ended; a run removed meanwhile answers empty with `missing` |
| `/api/usage?by=&since=&change=&unit=&include_estimates=` | the JSON `abk report --by <grouping> --json` prints |
| `/api/metrics` | every metric the code emits (name, type, attributes) with a chart's series, `source` (`prometheus` or `local`), the recent `traces` with their `source` (`tempo` or `local`), and `dashboard`, the pipeline dashboard's URL in Grafana (`<ABK_GRAFANA_URL>/d/abk-pipeline`) when set |

**Unit actions.** Each takes the unit store's lock with its real write hooks and logs
`chosen by the web UI` as the actor. *Requeue* is `abk requeue`'s own function; its body
may carry `mode` (`resume`, the default, `rework` or `restart`, as the CLI's flags). *Hold*
and *release* hand the poller's own dispatch a `hold` or `release` for the unit's pull
request, so the unit's thread, branch claim and depth rules are as for the label; they
change the pipeline's record only, not the label on the host, so a hold says to set the
label there too, and a release is refused while the last poll saw the label on the
pull request (remove it on the host). A unit being built answers 409 for those, as the
poller would defer. *Approve* is `abk approve`'s own function, `approve_unit`: it records
an approval decision (`approve`) for the unit's current review round with the head of its
pull request, and is refused for a unit with no pull request or no head and for a round
that already has a decision. Each refusal carries the CLI's reason, and the unit page shows the buttons disabled with it.

Any other path answers the built web UI, so `/units/<change>/<n>` loads on a direct visit;
an unknown `/api/...` path stays a JSON 404. The UI is built from `web/` (see below) and
is not in a checkout until `npm install --prefix web && npm run --prefix web build` (or
`uv run poe web-build`) has run; until then a page answers 503 saying so.

The pages:

- **Pipeline** (`/`): every unit under its `change/N` name with its state, its cause and
  who holds it (`held by: ...`, from the unit's record, never read out of the note).
- **A unit** (`/units/<change>/<n>`): the title, the state line, the unit's note and review
  round, its history as a timeline, and three tabs. *Status* lists the base, branch, pull
  request and dependencies (each links to its unit); *Logs* groups each
  run's lines by the node that wrote them, shows a reply whole and follows a live run until
  its outcome line appears, asking again after a failed read; *Usage* is the usage report
  filtered to the unit, by node. Above the tabs, the unit's action buttons; a disabled one
  shows its reason, and the page reloads the unit after an action succeeds.
- **Usage** (`/usage`): the report for a chosen grouping. In the unit grouping a key that is
  a unit's name links to the unit; placeholder keys such as `(none)` are plain text.
- **Metrics** (`/metrics`): every metric in a catalogue read from the code's telemetry
  calls, so a new one appears without an edit, each with its type, attributes and a chart.
  A line says whether Prometheus (`ABK_PROMETHEUS_URL`, summing samples over each window) or
  local files drew the charts; with no URL, or Prometheus not answering, they are derived
  from the usage ledger (cost, tokens, turns, and node and wait durations from its span
  lines), the ledger's `metric` records (tick and unit durations, review rounds, check
  failures, usage pauses) and the unit store (units by state). A second list shows the pipeline's recent
  traces from Tempo's search (`ABK_TEMPO_URL`), or, with Tempo unset or not answering, from
  the ledger's span lines, and says which. The `Dashboard` link opens the pipeline dashboard
  in the Grafana at `ABK_GRAFANA_URL`.

The front end lives in `web/` and is checked with `npm run --prefix web check` (prettier,
eslint with typescript-eslint and the react-hooks rules, `tsc`, vitest); `poe format` runs
it after pre-commit. Its tests render the pages against answers recorded from the real
server (`web/src/test/recorded`).

A field in `units.json` this release does not know is ignored on a read when it is empty. One
holding a value makes the read fail, naming the unit, the field and the value, the same way the
pipeline refuses that store; the page's API then answers with an error instead of a partial
view. Exit 0.

### `abk verify CHANGE`

Verifies one change by hand — after fixing what made the automatic
verification fail — and archives it if it passes. Deploys what the change's
merged PRs touched (`deploy.rules`), runs the live tests they added, records
the outcome in `runs/verified.json`. Exit 0 when the change verified and was
archived (printing what was deployed and what was archived); exit 1 with the
detail when verification fails, and exit 1 with a "verified but not archived"
line, naming the reason (already archived, not fully merged, withdrawn, or the
archive failed), when it passed but the change was not archived.

### `abk tags [CHANGE] [--all]`

Validates the task-group heading contract of one change's `tasks.md`, or
every active change's with `--all`: tags present and known, groups numbered
from 1, every group has tasks, `[contract]` paired with a last `[narrow]`,
`[acceptance]` present (as `e2e-test`, after everything it exercises) or opted
out with a reasoned `Acceptance: none — ...` line. Prints each problem with
its line, then the groups when clean. Also warns, once per group and
without failing, when a group can give its unit unrelated open parents: an `[acceptance]` or
`[narrow]` group after an `Independent:` group, an `Independent:` group followed by a later
group of its repo, or a `Needs:` to another change's same-repo group beside a same-repo
predecessor. Exit 1 if any change has a problem or no `tasks.md`.

### `abk check`

`openspec validate --all --strict --json` in the planning repo. Prints
OpenSpec's output; exit code is OpenSpec's.

### `abk e2e-test check [REPO]`

Lists each e2e-test split of the repo (default: every repo) and `rest` with its marker and the
number of tests it holds, found by listing through the profile from each declared project's
directory under the verify environment. It reports each selector the repo's test runner does
not know, each test selected by two splits (its identifier and both split names) and each
listing that fails (never read as an empty split). It runs no test and changes nothing. A
repo with no declared split passes with a line saying so. Exit 0 when it finds nothing; 1
when it finds something or a declared split cannot be applied by the profile; 2 for a repo
it does not know.

### `abk e2e-test hold SPLIT [--reason TEXT]`

Holds an e2e-test split (a declared split, or `rest`) until `abk e2e-test release`: units that wait on it
park, and a run leaves it out. It sets `hold: true` in `abk.yaml` as text and writes the
entry in `e2e-held.json` together, or neither; when the file cannot be edited that way it
prints the line to change by hand and writes nothing. It takes no deadline: no time ends a hold
set by hand, only `release` (or `hold: false` for the split in `abk.yaml`), and `--until` is an unknown argument. The command refuses a
name that is not a split and a configuration it cannot edit. Exit 0 when held; 1 when nothing
was written; 2 for a name that is not a split.

### `abk e2e-test release SPLIT`

Ends a hold: it removes the entry from `e2e-held.json` and the `hold` line in `abk.yaml`
together, or neither. When a `hold: true` of the configuration or an entry of the split's gate
still holds it afterwards, the command says so and what to change by hand. A split that is
not held prints `nothing changed`. Exit 0 when the split is released or was not held, 1 when
the edit of `abk.yaml` or the state file could not be made and nothing was written, 2 for a
name that is not a split. Both refusals leave `abk.yaml` and the state file as they were.

### `abk e2e-test status`

Prints each split and `rest` as `usable` or `held` (with the reason, and a file entry the
configuration overrides) and the splits the scheduled e2e-test run covers. Changes nothing.

### `abk archive CHANGE`

`openspec archive CHANGE --yes` in the planning repo, without the
all-merged and verified checks the tick applies. Exit 0; a failing archive
raises with OpenSpec's output.

### `abk openspec -- ARGS...`

Any other OpenSpec command, run in the planning repo through the configured
CLI (`openspec.command`, or `npx` with the pinned version). Exit code is the
command's.

### `abk gate [--repo DIR] [--base BRANCH] [--cache FILE] [--profile NAME]`

The tests-first gate for a branch in a checkout (default: the current
directory, against the remote's copy of the repo's `default_branch`, e.g.
`origin/dev` — the local branch of that name is yours, and nothing updates it;
`main` outside an installation): commits read as tests-then-implementation, lint
and format pass at each tests commit with type checking skipped, and the new
tests there fail for an accepted reason. `--cache` keeps results by patch-id
across restacks. `--profile` defaults to the profile `abk.yaml` gives the repo
containing `--repo`, else `python-uv`; it covers the files outside every project the repo
declares. Each test file is judged by the profile of its project, with that project's clean
and red commands run in its directory, and the gate fails if any project fails. Prints each problem prefixed `✗`; exit
1 if any, else 0 with `✓ tests-first: ...`.

### `abk approve UNIT`

Records your approval of the unit's current review round in the review store, together
with the head commit of its pull request at that moment, and prints the unit, the head and
the round. It merges nothing, pushes nothing and casts no vote on the host. It exits 1,
recording nothing, for a unit with no pull request or no head and for a round that already
has a decision. The web UI's approve button calls the same function.

### `abk attach release UNIT [--commit MESSAGE | --discard]`

Ends a chat's attachment to a unit without the server: the uncommitted changes a chat left
in the unit's worktree are committed (`--commit`) or thrown away (`--discard`), and the lease
is released, as one command. A dirty tree given neither is refused (exit 1, nothing changed),
as is any call while a step holds the unit's branch. A commit a hook rejects prints the
hook's output, exits 1 and keeps the changes and the lease; the command does not run the
unit's agent to fix what a hook rejects (the web UI's commit does), only the reformat retry.
A commit with nothing to commit exits 1 and keeps the lease. A commit already made and held
by a live server is left for that server to deliver. A clean tree is simply released.
A unit the tick held as `attached` stays held; `abk requeue` returns it.

### `abk requeue UNIT [--restart | --rework] [--note TEXT | --note-file PATH]`

Gives a `failed` or `held` unit another go. Three different things, and the
command says which:

- **Default: resume where it stopped.** Right when the failure was the
  environment's — a missing tool, a flaky check. A failed unit remembers the
  step it stopped at (say, before `verify`), its agent's work is on the branch,
  and redoing it would only spend the usage window to arrive at the same place.
- **`--rework`: keep the work and hand the agent the failure.** Right when the
  unit failed a check on real errors (a type error, a lint rule, a test), where
  resuming runs the same check on the same branch and fails the same way with
  the agent none the wiser. It clears the remembered step and keeps the saved
  output, so the next run is a rework from that output, then checks, then
  review. Refused (exit 1, nothing changed) when no failure was saved.
- **`--restart`: start over from the agent's step and forget the failure.**
  Right when the failure was the attempt's own, such as a build on the wrong
  base branch, where resuming would judge work that was never valid. It clears
  the remembered step and the failure the unit was handed.

**A person's note.** `--note TEXT` (or `--note-file PATH`) with `--rework` or
`--restart` records what a person wants as the unit's guidance, and the first
200 characters go in the requeue's history entry. The agent's next prompt, fresh
or resumed, shows it first, ahead of any saved failure or review text, as a
person's instruction that wins where the two conflict; the review of the work
that follows is told it too, and a rework commit clears it. With a note,
`--rework` accepts a unit with no saved failure, and the note is the whole ask;
a unit with no work on its branch yet builds tests first, the note shown to both steps.
A note with a plain requeue is refused (exit 1, nothing changed): a resume
re-runs a step without reading it. Pull request comments are unchanged, and the
note is not posted to the pull request.

A unit with a `Needs:` line whose dependency is not yet in review (or, in another
repo, merged) is not resumed: it goes to `planned` with the cause `gated`, keeping
its thread, branch and saved failure, and the command names the group it waits for.
`abk status` lists it as waiting. Once the dependency is ready, the next tick
delivers the requeue in the mode it was given (default, `--rework` or `--restart`).

Any other state is refused: a running unit would be built twice, an in-review
one has a pull request that would be orphaned, and a planned or merged one has
nothing to retry. `--rework` and `--restart` cannot be combined. `--restart` does not touch the unit's branch or worktree; if
those came from a wrong base, remove them first (`git worktree remove`, then
`git branch -D`, after checking nothing on it is unpushed). Exit 2 for an
unknown unit, 1 when the unit is not stuck, else 0.

A unit never has to be requeued out of `running` by hand. At the start of each
pass, a `running` unit whose branch lock names a process that is gone is
failed with the note "the run ended without recording its outcome", and can then
be requeued as above. One with a live holder is left, and so is one with no lock
(or an unreadable one) at all, which the pass reports. So is one with a thread,
or one the pass is holding: a run killed in a node resumes from its thread. Recording an outcome reads the unit store again
once, after a second, when the first read fails; if the second fails too, the
unit is logged as stranded and the error is raised as before.

### `abk replan [CHANGE|UNIT ...] [--all] [--failed] [--forget]`

Plans changes again now, whatever their recorded plan says. A tick plans a change
only when its `tasks.md` changes (or its last plan failed and attempts remain);
this is the way to ask for a plan otherwise. For each selected change it drops the
recorded plan, asks the planner, and links the `Needs:` lines, the two steps a tick
performs, so the units stored are what the next tick would have produced. It first
says how many model calls it will make.

- **Selecting.** Names are the folders of the active changes. A unit id
  (`feature/2`) is mapped to the change that carries it, and the command says so.
  `--all` is every active change; `--failed` every change whose last plan failed
  or gave up. With none, the command lists each change with the state of its plan
  (`planned`, `failing 2/3: <reason>`, `given up` with `abk replan --failed` to plan it
  again, `waiting for the network` or `waiting for the model service` with the time of
  the next try and the attempts, which a wait does not use, `never planned`), plans
  nothing and exits 2. A change that meets the outage again prints that it is waiting
  and that no attempt was used, and exits 1. `--failed` selects a waiting change.
  A planner prompt that is too large shows as `failing 1/3: the generic prompt for feature is
  2000001 bytes; the stdin transport carries at most 2000000`; it counts attempts like any
  other failure.
  A plan that was refused shows the reason after its state (`failing 1/3: unit
  feature/2 claims group 1, which a merged unit has already built …`).
- **`--forget`** clears the records and stops: no model call, and the next tick
  plans them.
- **Started work is left alone.** A unit that is running, in review, failed, held,
  merged or satisfied keeps its state, branch, pull request and history. A planned
  unit takes the new shape; an unstarted one the plan drops becomes `unplanned`.
  Dependencies are rebuilt from the plan, so a stale one is removed, and the `Needs:`
  lines are linked again on top.
- **It prints what differs** from before: dependencies added and
  removed, estimate and tier changes, units that became `unplanned`, joins dropped,
  and each started unit it left alone (`kept: feature/1, running`); nothing for a
  unit that did not change, or "nothing changed".

A name that is not a change, a change without a `tasks.md` and a change with
task-group tag errors (run `abk tags`) are refused and nothing is planned for them.
Exit 0 when every selected change planned, 1 when any failed or was refused, 2 for
a usage error.

## Setting up

### `abk init [PLANNING_DIR] [--repo PATH ...] [--consumes REPO:CONSUMED[,CONSUMED] ...] [--yes] [--skip-research] [--skip-propose] [--force] [--update-rules] [--dry-run] [--runtime NAME] [--agent-command ARGV] [--set KEY=VALUE ...] [--runtime-config FILE] [--policy-only] [--policy-fix ARGV] [--run-policy-fix] [--register-store ID]`

Creates a planning repo for a set of checkouts; the one command that creates
an installation rather than reading one. Step by step in [init.md](init.md).

- `PLANNING_DIR` defaults to `.`.
- The next steps end with the lingering advice (`sudo loginctl enable-linger <user>`)
  when lingering is off, since timers only run while the user manager does.
- `--repo PATH` (repeatable) names a checkout; with none and without `--yes`,
  paths are prompted for one per line.
- `--consumes app:platform` overrides what a repo consumes (detected from its
  dependency references otherwise).
- `--yes` skips the prompt. `--skip-research` / `--skip-propose` skip the
  model-driven steps. `--force` overwrites `abk.yaml`, `openspec/config.yaml`,
  the recommendation documents and the generated changes. `--dry-run` prints
  the `abk.yaml` that would be written, runtime choice included, and the plan,
  and stops.
- The runtime is chosen after the repos are detected and before any agent step:
  `--runtime` and `--agent-command` name it, `--set key=value` (repeatable, the
  key being where the answer is written in `abk.yaml`, e.g. `models.review`)
  and `--runtime-config FILE` (a YAML fragment of `abk.yaml`) give any other
  answer. Every route is validated like a typed answer, and an unknown key
  exits 2 naming it. Without `--yes` it also asks what a candidate needs and
  which models to use (from what the agent advertises, Claude Code's
  documented aliases, or a typed name; never by asking a model), shows the
  fragment it will record and writes only on a yes: declining prints
  `nothing written` and exits 1. `--yes` is the confirmation for a fully
  specified run; a usable-runtime problem (none, several without `--runtime`),
  a bad flag value or an unknown key exits 2, writing nothing.
- `--update-rules` brings `openspec/config.yaml` up to the framework's rules
  version and does nothing else: it adds, to the end of the `context:`, the
  paragraph each newer version added, and restamps the file. The wording, the
  comments and the rules are left byte for byte, and `abk.yaml` is not read.
  A second run changes nothing. A file with no `# abk-rules:` stamp, a newer
  stamp, or a version that changed more than the context is refused, and the
  file is left alone. Review the diff and commit it; this is what `abk doctor`
  points to when the stamp is behind.
- `--register-store ID` runs `openspec store register --id ID --yes` on the
  planning repo.
- The guided policy step runs once `abk.yaml` is written, before research,
  propose and the commit, so whatever it records is part of init's commit. It
  checks the selected runtime (`runtime`, or `ABK_RUNTIME`) the way
  `abk policy check` does: it reads the agent's own configuration, starts no
  agent, spends no tokens and asks no question, with or without `--yes`. Each
  class is printed with the pattern that refused it, and a class not refused
  by class and spelling. The fix is, in order: the
  installation's `runtimes.<name>.policy_fix`; else, for an agent the kit can
  write to (a known agent whose row has an applier), the kit's recommended
  policy; else the choices below. For a configured fix, the command and the
  unrefused classes are printed, init asks, runs the command only on a yes with
  its output on your terminal (never captured), checks again and prints each
  class and spelling as refused or not. For the kit's recommended policy, init
  shows the agent's configuration path and the diff (added lines only), asks
  `apply the kit's recommended policy? [y/N]`, applies the deny list only
  (backing the original up once, as `abk policy apply` does), checks again and
  prints each class and spelling as refused or not; a spelling still not refused
  is named, with the note that the agent's own matcher, not the list, may be
  what lets it through. A no writes nothing and states what is still unenforced.
  An agent whose configuration is absent is reported as `not found`, nothing is
  offered and `abk policy patterns` is named. The build-run toolset is never
  changed here; `abk policy apply --toolset` is named as a separate decision.
  A fix that exits non-zero is reported with its status and the check still
  runs again; one that exits 0 and changes nothing prints `the fix made no
  change; still not refused: <spellings>`; a pass is only reported when the
  second check showed it. An agent with neither a fix nor an applier offers two
  choices, none guessed (and the menu says `abk policy patterns` prints the
  recommended patterns to place in its configuration yourself): rely on abk's own protocol layer (it sees what the agent asks
  about, not what it never asks about), or supply a fix command (an existing
  executable, recorded as `policy_fix`). With `--yes` a configured fix, or the kit's recommended policy, is only
  named, never run, unless `--policy-fix` or `--run-policy-fix` is also given. No answer is
  kept between runs; each check reads the file again.
- `--policy-only` runs just that step on an existing installation: it reads
  `abk.yaml`, detects no repo, runs no research or propose and makes no
  commit; `--runtime NAME` names another entry already in the file. It writes
  `runtimes.<name>.policy_fix` only when you chose to
  record it in this run. Exit 0 when the check passes after the step, 1 when a
  class is still not refused, the configuration is absent or unreadable, or the
  agent cannot be checked (`cannot check: abk has no policy for this agent`), 2 with no
  `abk.yaml`, an unknown runtime or a flag that cannot combine with it
  (`--repo`, `--consumes`, `--update-rules`, `--force`, `--dry-run`, the
  runtime-answer flags), writing nothing. When it passes on an entry marked
  `policy: unchecked` it says to remove that line so doctor checks it again.
- `--policy-fix ARGV` supplies the fix, validated as an existing executable
  (exit 2 otherwise), recorded as `policy_fix` after a confirmation (`--yes`
  is the confirmation) and used in this run, with or without `--policy-only`.
  `--run-policy-fix` lets `--yes` run a configured fix, or apply the kit's
  recommended policy, unasked: a fix rewrites
  the agent's own configuration, so `--yes` alone never runs one and, with a
  class not refused, names it and exits 1 under `--policy-only`.

Exit 2 when a repo path is not a directory, two repos share a name, or
`--consumes` names an unknown repo; 1 when the layout fails (git or
`openspec init`) or a generated change did not validate after its repair
round (its files are left to finish by hand); 0 otherwise. `--policy-only`
has its own codes, above.

### `abk install-skills [--repo PATH ...] [--user]`

Copies the three abk skills into `.claude/skills/` — of each `--repo`, of
the user-level skills directory with `--user`, or (with neither, and an
installation found) of the planning repo and every checkout in `abk.yaml`.
A skill file the framework wrote (its `generatedBy` header) is overwritten
with the current version; one written by hand under the same name is refused
and left alone. Exit 2 with no target and no installation; 1 if any file was
refused; else 0.

### `abk install-timers [--no-enable] [--remove] [--dry-run]`

Puts this installation's systemd units on this machine: the tick every five
minutes and the three scheduled tracks, each a `.service` and a `.timer` in the
user manager's directory (`$XDG_CONFIG_HOME/systemd/user`). Rendered here
rather than at `abk init`, because a unit carries an absolute
`WorkingDirectory`: one written into the planning repo names whoever ran init,
and everyone who cloned it afterwards got units aimed at someone else's home.

- **Named for the installation.** `abk-<planning dir>-tick.service`, so several
  installations on one machine do not replace each other's units. Two planning
  repos *both* called `planning` would collide, so the second install refuses
  and names where the first lives; give one of them a different directory name.
- **Finds its tools.** A unit starts with no login environment, so its `PATH` is
  fixed by the template, and a tool that is on yours is not necessarily on the
  unit's. On WSL the Azure CLI is the Windows install, which only a login shell
  carries: every command you ran by hand worked while the scheduled poll of the
  Azure repo failed on every tick. The install therefore asks *this* shell where
  `uv`, the agent's command and each repo's forge client (`gh`, `az`) live, and
  appends the directory of any that is not already on the unit's `PATH`. It says
  which it added, and warns about a tool it cannot find. `abk doctor` checks the
  installed unit's own `PATH` against the same list (`timer PATH`), and a failed
  poll is written to the tick's log.
- **Enabled by default.** Written-but-not-enabled is the failure that looks most
  like success: the units are there, `abk status` answers, and no tick has
  happened in a week. Only the timers are enabled, never the services beside
  them, which would run at boot outside the schedule. `--no-enable` writes the
  files and leaves scheduling to you.
- **Needs lingering.** Timers only run while the user's systemd manager does, and
  without lingering that is only while a login session is open (on WSL and on a
  server, none stays open). After enabling, the command checks
  `loginctl show-user <user> --property=Linger`; when it is off it tries
  `loginctl enable-linger <user>` without `sudo` or a prompt, and if that fails
  prints `sudo loginctl enable-linger <user>` with the reason. It never runs
  `sudo`, says nothing when lingering is on or `loginctl` is missing, and skips
  the check with `--no-enable`, `--dry-run` and `--remove`. The enable attempt
  passes `--no-ask-password`, so no polkit dialog appears. A shell logind has no
  record of (some `su` and container shells) makes `loginctl show-user` fail, which
  is reported as unknown and stays silent even though lingering is off there.
- **Repeatable.** A unit that already holds the right content is left alone,
  down to its modification time, and systemd is told nothing when nothing
  changed. Safe in a setup script that runs on every boot.
- **Self-healing.** Units of *this* installation that the current version no
  longer installs are stopped and removed: the unnamed `abk-tick.service` an
  earlier version wrote, or a unit a later version dropped. Ownership is where a
  unit *points* (its `WorkingDirectory`), never what its name starts with, so
  installation `meta` cannot remove `meta-agent`'s. Another installation's
  units are never touched, however out of date.
- `--remove` stops, disables and deletes this installation's units, outdated
  ones included. `--dry-run` prints what would be written or removed.

A file with the same name that this framework did not write is refused, not
overwritten. Exit 1 if anything was refused; else 0; 2 with no installation.

### `abk doctor`

Is this installation in a state the pipeline can run in? Each check prints
`ok`, `warn` or `FAIL` with a one-line fix; exit 1 if anything failed, else 0.

| Check | FAIL when | warn when |
|---|---|---|
| config | `abk.yaml` is missing, malformed or has an unknown key; or the runtime selected (`ABK_RUNTIME`, from the environment or the planning repo's `.env`, else `runtime:`) is unknown, or is missing a fact it requires under `runtimes.<name>` | |
| worktree root | `planning.worktree_root` is inside the planning repo | |
| repo `<name>` | the path is missing, not a git checkout, or git has no `user.email`/`user.name` for it (repo-local or global — the line says which scope signs, so a workspace whose repos belong to different accounts can see one identity covering them all) | |
| forge `<name>` | the repo's host will not answer for it: the forge's `check_access` fails (GitHub: `gh` holds no token for the owner; Azure DevOps: the repo cannot be read with the PAT or `az` session) | |
| merge guard `<name>` | | *note, not a warning:* nothing server-side refuses a merge on the default branch (no branch protection or policy), so the command policy hook is the only guard. A free private repo cannot have one, and a warning there would be permanent and unfixable |
| linger | the timers are installed and enabled but lingering is off, so they stop with the last login session; the fix is `sudo loginctl enable-linger <user>`. Nothing when it is on, no timers are installed, or `loginctl` is missing |
| timers | | the units are installed but a timer is not enabled, or one is missing, out of date, or left over from an earlier version (each named). A note when none are installed — something else may run `abk tick` — or when `systemctl` cannot be asked |
| stale timer units | | a unit this framework wrote, for any installation, points at a directory that no longer exists. Nobody is left to remove it, and `systemctl enable` accepted it without complaint |
| node, openspec | `node`/`npx` are not on PATH, or the OpenSpec CLI does not run | |
| runtime | the selected runtime is not implemented, or its agent command (`runtimes.<name>.command`, else the adapter's own, `claude` for `claude_code`; the one every run spawns) is not on PATH | |
| runtime coverage | | the runtime's `policy_coverage` is short of `all_calls` |
| runtime policy | the runtime does not refuse a forbidden command class or one spelling of it (each class is named, with the spelling it let through and the spellings it refused; the fix printed is `runtimes.<name>.policy_fix`, else the runtime's own advice). It reads the agent's configuration, starts no agent and keeps no answer; the line says the answer is what the configuration says, not observed from the agent. Also when the configuration is absent or unreadable (the path or reason is named) | `cannot check: abk has no policy for this agent`; not checked, because the agent command does not resolve (see the `runtime` check) |
| gate usage | | a split's gate cannot be read: the provider's library is not installed (both forms of the fix are printed: `uv sync --extra modal` in the installation, or `agent-build-kit[modal]` in its dependency on the kit), the call raises (the error's class and redacted message), the gate command is not on PATH, or the result is unknown. A reading that holds the split is a note, not a warning. The doctor reads afresh and never from the cache; a workspace with no gate has no such check |
| ssh key `<name>` | `deploy.ssh_key` does not exist | |
| verify.env `<VAR>` | the provider cannot resolve (names only; never values) | |
| rules | | The `# abk-rules: vN` stamp in `openspec/config.yaml` against the framework's rules version: a note when it is unstamped, a warning when the framework has added rules since (they are listed) or the stamp is newer. Wording is never compared. |
| abk.yaml `<name>` | | a service directory with no deploy rule, a rule prefix that no longer exists, a dev-stack script without `dev_stack`, a `live_written` path that is not a directory |
| skills `<target>` | | an installed abk skill is older than the framework |
| `<repo> <tool> version` | | a tool in `pyproject.toml`'s dependency groups is also run from a hook repository with its own `rev` in `.pre-commit-config.yaml`, so two versions can disagree. Only checked for repos with both files |
| `<repo> <tool> hook` | | a `repo: local`, `language: system` hook runs `uv run <tool>` for a tool absent from the dependency groups, so it fails. Only checked for repos with both files |
| notifications | `notifications.provider` is `windows` and `powershell.exe` does not list the pinned BurntToast version (the fix is the install command `abk init` offers), or is `command` and the `show` program is not on PATH. Not listed while the provider is `off` | |
| replay cassettes `<repo>` | | a recording has waited for review through more than `tests.replay.review_after_runs` runs. A note, not a warning, when some wait but none past the limit. Only checked for repos with a `tests.replay` section |
| telemetry traces / telemetry metrics | | `ABK_OTEL_ENABLED` is set and the signal has no endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`, or the per-signal one), or the endpoint does not answer. Only checked when enabled |

### `abk config [--show | --path | --migrate [--yes] [--dry-run]]`

`--show` (the default) prints the effective configuration as YAML with every
default filled in; `--path` prints the `abk.yaml` in force. Exit 0.

`--migrate` edits the file's text, so comments and spacing stay: the root `limits` block
becomes `global_limits`, and the three scheduling settings left in it move to
`project_limits`. It prints the diff and asks; `--yes` skips the question and `--dry-run`
prints the diff and writes nothing. The first original is kept as `abk.yaml.abk-backup`,
and the write goes through a temporary file. Exit 0 when it wrote or had nothing to do,
1 when not confirmed (or no terminal and no `--yes`), 2 when it refuses and writes
nothing. `--yes` and `--dry-run` need `--migrate`.

### `abk project init PATH --profile NAME --repo REPO [--scaffold]`

Registers a project in `REPO`'s `projects:` list before its directory exists (it is
pending until it does). `PATH` is relative to the repo root; an absolute path under the
repo is stored relative, and one outside it (or with a `..` part) is refused. The entry is added to the file's own lines, so comments, key
order and quoting stay as they were; a `projects:` written inline is refused rather than
rewritten. It refuses a path the repo already registers, a profile that is not
registered and a repo that is not in `repos:`, each leaving `abk.yaml` unchanged and
exiting 1. `--scaffold` also writes the smallest manifest the profile's detection
recognises under the new path (the profile supplies it) and leaves an existing manifest
alone, saying so.

### `abk planning split --repo REPO --to DIR [--project PATH] [--allow-mixed source|destination] [--spec CAPABILITY ...] [--scrub] [--remove] [--apply | --dry-run]`

Moves a repo's changes, archive entries, specs and unit records from this planning repo
to another installation. It is a dry run unless `--apply` is given (`--dry-run` spells
the default and is a usage problem with `--apply`): the plan prints the source,
destination and selection, a count for each of changes, archive entries, specs, units,
plan records and config entries, each refusal as its own line, the uncommitted files it
read, the `--scrub` counts, and a last line saying nothing was written. `--repo` names
the repo whose changes move; `--project` moves only the groups tagged for that project of
it. A change is moved, staying or mixed by its groups' tags; a mixed change is refused
unless `--allow-mixed source` keeps it or `--allow-mixed destination` moves it whole. A
spec moves with the changes that wrote it; `--spec` moves one nobody's delta touches. Units
of moved changes move with their records; a unit in `running`, `in_review` or `held`, one
that spans a staying change, and a dependency that would dangle are refused.

`--to` must already be an installation (`abk init DIR`). Files are copied without
overwriting a different one; `--scrub` strips installation names and home paths from the
moved text and the records' free text, never an id or code. `--apply` also adds the repo's
entry to the destination's `abk.yaml`.

`--remove` (with `--apply`) re-reads the destination, and only if every file and record
matches removes from the source the moved files (a directory only when empty), unit
records, plan records and, when nothing there names it any more, the repo's entry; if
something does, it prints `kept repo KEY: still named by ...` and exits 1. The usage
ledger, spec snapshots, run logs and staying changes are never touched. Without
`--remove` the source is not written at all. A second run prints `nothing to do`.

Exit 0 when nothing is refused, 1 when anything is (or a copy fails verification), 2 for a
usage problem or an installation that does not load. Order: make the destination with
`abk init`, settle the units, read a dry run, `--apply`, then `--remove`.

### `abk policy patterns [--format glob|json|yaml-list] [--class LABEL ...] [--extra]`

Prints the kit's recommended command globs, for an agent whose configuration the kit cannot
patch. It needs no installation, makes no model call and writes no file. `--format glob`
(the default) prints one glob per line; `json` a JSON array; `yaml-list` a YAML sequence of
double-quoted scalars, safe for the quotes, brackets, colons and `*` in the globs. Each loads
back to the same list, in table order. `--class LABEL` limits the output to that class's globs
and can be repeated; the labels are the ones `abk policy show` prints. `--extra` adds the
selected runtime's `runtimes.<name>.policy_extra` after the kit's globs, none repeated, and
needs an installation. Exit 0; 2 for an unknown class (the classes there are are named), or
for `--extra` with no installation or one that does not load.

### `abk policy show`

Prints the recommendation per class with its globs, the classes it has no glob for and why,
its known false positives and its glob dialect. It needs no installation, changes nothing and
does not run the policy check; `abk policy check` and `abk doctor` do. With an
installation (or `--runtime NAME` / `--agent NAME`) and an agent whose configuration the kit can
read, it then compares that configuration with the recommendation: the missing globs by class
(and the installation's `policy_extra` that are missing), a count of the entries that are not the
kit's (never listed), and the toolset recommendation against its current value. An absent or
unparseable configuration is said so, naming its path. An agent the kit cannot read, or whose
command the table does not recognise, says so and points at `abk policy patterns` and `--agent`.
Exit 0; 2 for an `--agent` or `--runtime` that names nothing.

### `abk policy apply [--runtime NAME] [--agent NAME] [--dry-run] [--yes] [--toolset]`

Merges the recommended globs (then the runtime's `policy_extra`) into a known agent's own
configuration. It prints the diff, asks `apply to <path>? [y/N]`, then writes: the original is
copied once to `<file>.abk-backup` (the path is printed), the write is atomic, and only lines
are added, so the rest of the file stays byte for byte. It starts no agent: its closing line
names `abk policy check` as the way to confirm, which reads the configuration and spends no
tokens.

### `abk policy check [--runtime NAME] [--agent NAME]`

Judges every probe command against the deny list in a known agent's own configuration, with
abk's matcher, and prints each class and spelling with the pattern that refused it or `not
refused`. The classes the recommendation leaves to the person are marked `not covered by
design` and never fail it. It ends with the label, `what the configuration says, in abk's
dialect; not observed from the agent`. It starts no agent, spends no tokens, changes nothing
and keeps no answer. `--agent NAME` checks that known agent's configuration for a wrapper
command. Exit 0 when every covered class is refused; 1 when one is not, the configuration is
absent or unreadable, or the agent cannot be checked (`cannot check: abk has no policy for
this agent`); 2 for a usage problem, such as an unknown `--agent` (the known agents are
named).

The agent is the known agent the runtime's command starts; `--agent NAME` names the row when the
command is a wrapper the table does not recognise, and `--runtime NAME` reads another runtime's
entry than the installation's. Without an installation `--agent` is required. A runtime with no
command (its enforcement is built in) has nothing to apply. `--dry-run` prints the diff and
writes nothing; `--yes` takes the place of the answer; the two together are a usage problem.

`--toolset` also replaces the agent's toolset list with the recommended one, shown as
`from [...] to [...]`. It is a separate flag because it replaces rather than adds: a deny entry
only makes the agent refuse something, while a toolset narrows what a build run may call at
all, and a person with their own tools has to choose that. Without it the recommendation and the
current value are stated and the list is left alone. The flag on a row with no toolset is a usage
problem.

Exit 0: written, nothing to change, or a dry run. 1: the person declined. 2: a usage problem, an
absent or unparseable or wrong-shaped configuration (the file and key are named), an unknown
`--agent` or `--runtime`, or an agent with no applier (the patterns command is printed).

### `abk changelog check [PATH]`

Checks a changelog's form: no conflict marker, a blank line between bullets, no bullet
repeated, every bullet under a `##` section, headings in order. Each problem prints as
`path line N: message`, and the exit is 1 when there are any. With no `PATH` it reads the
file named by the `changelog` setting of the repo the current directory belongs to (a
worktree included). A missing file passes with a note; so does a repo with the setting
`null`. Unit-test runs it for every repo with the setting on.

### `abk scrub-check --target DIR [--show-terms]`

Run *from an installation*, greps `DIR` (a framework checkout) for anything
that names this installation. The terms are derived from `abk.yaml` each
time — the planning directory name, repo names, each host identity's parts and project
names, checkout directory names, `live_written` names, the ssh key name, the
credentials array, the first path segment of each deploy rule and the words
of its commands, `verify.env` variable names — minus generic words
(`docker`, `deploy`, `main`, ...) and anything under three characters,
case-insensitive. Prints `path:line: term` per hit; `--show-terms` prints the
list. Exit 2 if `DIR` is not a directory, 1 with hits, 0 when clean.

The planning root's own name is a term only when it is not the target: a root whose repo
entry has path `.` is the checkout naming itself, so scanning its own checkout does not
report the root's name. Terms also come from the home and literal-value facts of the merged
configuration (`verify.env` literals, `env-file` provider paths under a dot-directory, the
home user's name). A gitignored `scrub.local` in the planning root adds terms, one per line:
`#` starts a comment, a blank line is skipped, `!word` removes a derived term, and a term
under three characters is dropped. A word on the generic list written there is kept.

### `abk scrub-store [--apply]`

Finds home-directory paths in the text fields of the unit store (`feedback`, `guidance`,
`predecessor_note`, `stack_refusal` and each history note). The default is a dry run: it
prints each record, field and count, never the text, and changes nothing. `--apply` needs a
paused pipeline (`abk pause`); it keeps one original as `units.json.pre-redact` beside the
store (ignored by `.gitignore`, the same suffix `abk redact-history --apply` writes),
replaces each Linux, macOS or `~` home prefix with `<home>/` keeping the rest of the path,
and writes every changed record in one write. Other terms, such as a repo name, stay in the
text. A second `--apply` finds nothing, writes nothing and leaves the first copy alone. Exit
0 on success, 1 when `--apply` runs without a pause (the pause is named and nothing changes).

## Tracks

### `abk track PHASE [--project NAME] [--focus TRACK|RUN_ID] [--dry-run]`

Runs a scheduled track now, for every eligible repo or just `--project`.
`PHASE` is `health` (daily read-only pulse check), `improve` (weekly discovery
then a propose pass), `recommend` (weekly bigger-picture discovery then a
propose pass) or `propose` (turn the existing backlog into an OpenSpec
change for the pipeline to build; `--focus` says which run-log entries to
read first). A track never edits a repo or opens a pull request. `--dry-run` prints each rendered
prompt's opening lines and the `claude` command without the usage check, the
pulls, or running anything. Details in [tracks.md](tracks.md). Exit 1 if any
repo's phase exited non-zero or could not be pulled, else 0 — including when
there was no headroom or no eligible repo.
