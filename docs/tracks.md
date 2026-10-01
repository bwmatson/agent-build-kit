# The scheduled tracks

Beside the unit pipeline, four **tracks** keep watch on the repos: `health`,
`improve` and `recommend`, which look, and the `propose` pass the first three
hand off to, which turns what they found into an OpenSpec change. Each is a
Claude Code run against one repo with a Markdown mission prompt; `abk track
PHASE` runs one now, and `abk install-timers` writes systemd timers for the
three scheduled ones.

**A track never edits a repo or opens a pull request.** `propose` writes a
change in the planning repo; if it validates, the runner commits it to the
planning repo's default branch, and the pipeline's tick plans and builds it
like any other change — units, a review loop, the test tiers. Work a track
wrote straight into a repo would go around all of that, and the tick would
later find it already done.

| Track | Cadence | Reads | Writes |
|---|---|---|---|
| `health` | daily | logs, resources, LLM observability, pipeline state, secrets — "is something actually wrong right now" | a run log with a `**Status:**` line; `propose` straight away on `ATTENTION`/`URGENT` |
| `improve` | weekly | lint and types, dependency staleness, README drift, convention adherence — "this could be better" | a run log; then `propose` |
| `recommend` | weekly, another day | test coverage gaps, technical debt, architecture opportunities (the one with web access), cost/performance — bigger-picture, mostly for a human | a run log; then `propose` for the rare bounded finding |
| `propose` | after the above, or on demand | the run logs' "Actionable candidates" and `tracked-issues.md` | one OpenSpec change of up to `tracks.propose_max_issues` task groups, committed to the planning repo's default branch if it validates |

## The per-repo flow

`run_track` (`tracks/runner.py`):

1. **Headroom.** The usage guard's `may_start_unit` decides; with none the run
   logs why and exits 0. The next timer is the retry, as it is for the
   five-minute tick.
2. **Pull the planning repo** to its default branch (`git checkout`, `git
   pull --ff-only origin`), since every phase writes and pushes its run log
   there. `planning.self_pull: false` skips this. A failed pull is fatal.
3. **Eligible repos**: each `abk.yaml` repo (or only `--project NAME`) whose
   checkout is a git repo, whose `origin` is a remote some forge recognises
   and names the same repo `abk.yaml` does, and whose host answers for it
   (`forge.check_access`). Anything else is logged and skipped, so a repo can
   be listed before it exists on its host.
4. Per repo, in `abk.yaml` order: pull its default branch (a failure skips
   the repo and counts as failed), then dispatch:
   - `health`: one phase. Afterwards the run log's `**Status:** OK |
     PENDING RESOLUTION | ATTENTION | URGENT` line is read back; `ATTENTION`
     or `URGENT` — a genuinely new finding, not one already in flight — runs
     `propose` for the same repo now. A missing or unparseable status means
     "can't tell", and nothing more happens.
   - `improve`, `recommend`: the discovery phase, then `propose` — always,
     even when discovery exited non-zero; propose falls back to the
     candidates the run logs already hold.
   - `propose`: one phase, run in the planning repo with the repo's checkout
     readable beside it. See [What `propose` writes](#what-propose-writes).

No phase carries a dollar budget — every one of them is bounded the same way
as the headroom check in step 1: the usage window is the limit, read live.
A guessed dollar ceiling beside that drifts from real cost, and set too low
it refuses to start a run instead of bounding one.

Exit 1 if any repo's phase exited non-zero; a non-zero exit is never fatal to
the next phase or repo.

Each discovery phase is one `claude -p` call, run with the repo's checkout as
the working directory:

```
claude -p --add-dir <planning root>
  --permission-mode acceptEdits
  --allowedTools "<tracks.allowed_tools>" --disallowedTools "<tracks.disallowed_tools>"
  --model <tracks.model> --output-format json <prompt>
```

The raw JSON goes to `<planning root>/<tracks.raw_output_dir>/<run id>-<repo>-<phase>.json`
(`.last-runs/`, gitignored). `propose` is the same call turned around: the
planning root is the working directory and the repo's checkout is the added
directory.

What a track agent may run is the tool allow/deny lists in `abk.yaml`, which
deny force pushes, hard resets, recursive deletes, branch force-deletes, and
every forge's way of merging a pull request — plus a policy hook that refuses
creating or switching a branch, a reset, a forced branch move and a
cherry-pick aimed at the planning repo (the pipeline commits there). The same
git aimed at the code repo's checkout is allowed.

The hook fences file writes in the planning repo by path, not by checkout,
because `propose` has the planning repo as its own checkout and everything in
one's own checkout is ordinarily one's to write. A discovery run may write its
run log and the tracker (the Markdown under the state directory) and nothing
else there; a `propose` run may write those and the one change it was named
(`__PROPOSED_CHANGE__`). The tick's live state (`runs/units.json`), `abk.yaml`
and the specs stay out of reach of both.

## Run logs and the tracker

Every phase writes a run log at `<state_dir>/<run id>-<repo>-<track>.md`
(`runs/20260101-064700-app-health.md`, say), where the run id is the process
start time. The path is injected into the prompt, not left for the agent to
invent: health's status readback depends on it being predictable.

The prompts share a shape. Each phase first refreshes
`<state_dir>/tracked-issues.md` — the workspace-wide list of findings with a
change in flight ("Pending resolution") or declined ("Rejected"). An entry
names a change, and is checked against where that change has got to: archived
under `changes/archive/` means it merged, still under `changes/` means it is
in flight, neither means it was rejected or dropped. (An entry from before
tracks wrote changes names a PR instead, and is checked with `gh pr view`.)
The phase then checks whether the previous run's `[not-yet-actioned]`
candidates were fixed by hand since (marking them `[actioned — commit
<hash>]`), fans the category playbooks out to subagents, cross-references
findings against the tracker so a problem already in flight is not proposed
again, and writes the log with an "Actionable candidates for the next propose
run" section. `propose` reads those sections most recent first, groups
candidates by underlying issue, picks up to `propose_max_issues` distinct,
well-evidenced, bounded ones, writes one change with a task group per issue
(its failing test first), adds a "Pending resolution" entry per issue, and
marks the source candidate `[proposed — <change>]`. After every phase the
runner — not the agent — commits the Markdown under the state directory (the
run log and tracker edits; never the tick's live state there), and after
`propose` the change it wrote, to the planning repo's default branch and
pushes. A push the remote rejected is retried once
after a fast-forward; a second rejection is logged and the commit is kept. If
the agent left the planning repo on another branch, the runner checks the
default branch out again, keeps the stray branch, and logs its name; if the
default branch was rewritten, the run stops and nothing is committed. A tick
also checks the default branch out, and logs the branch it found, before it
reads state.

`--focus` on `propose` biases which entries are read first: a track name
resolves to that track's most recent run log for the repo; a run-id prefix
resolves to the matching log (preferring the source track's over the run's
own `-propose.md`, and over the `-implement.md` the phase left before it
stopped editing code). Neither changes what qualifies.

## What `propose` writes

`propose` writes one OpenSpec change, named `<repo>-track-<run id>`, under
`<specs_dir>/changes/`. The hook grants it that directory, its run log and the
tracker, and nothing else in the planning repo.

The runner — not the agent — then settles the planning repo:

1. **Validate.** The change goes through the same check `abk init` gives a
   proposed one: `openspec validate`, and the tasks-tag contract `abk tags`
   enforces, against this workspace's repos. The runner commits straight to
   the default branch and the tick plans whatever is in `changes/`, so this is
   the only check between a timer-written spec and the pipeline. A change that
   does not validate is worse than none: the tick reads it, cannot plan it, and
   says so a cycle later with nobody present.
2. **Commit.** A valid change goes in one commit with the run log and tracker
   edits, pushed to the default branch. Not a pull request: the review the
   change gets is the pipeline's, on every unit it becomes.
3. **Or set aside.** An invalid change is moved to
   `<state_dir>/rejected-changes/<change>/` — out of `changes/`, which the tick
   reads, but not thrown away — and a note,
   `<run id>-<repo>-propose-rejected.md`, listing what failed is committed in
   its place, so the tracker does not claim a change is in flight that never
   was.

A run that wrote no change is fine; nothing surviving is a valid outcome. A run
cut short by the usage window goes through the same validation, so half a
change is never committed.

## Prompts and placeholders

The prompts are package data under `tracks/prompts/`: `health.md`,
`improve.md`, `recommend.md`, `propose.md`, and `categories/<track>/*.md`
playbooks the top-level prompts fan out to by path. The four top-level files
are rendered with these tokens; a prompt using any other `__TOKEN__` is an
error:

| Placeholder | Value |
|---|---|
| `__RUN_ID__` | this process's run id |
| `__RUN_LOG__` | the run log path for this repo and phase |
| `__PROJECT__`, `__PROJECT_DIR__`, `__PROJECT_REPO__`, `__PROJECT_REPO_URL__` | the repo's `abk.yaml` key, checkout path, identity, web URL |
| `__PROJECT_DESCRIPTION__`, `__PROJECT_CONSUMES__` | the repo's `description` and `consumes` |
| `__WORKSPACE_REPOS__` | a bullet list of every repo with its description |
| `__PLANNING_DIR__`, `__STATE_DIR__`, `__PROMPTS_DIR__` | the planning root, the state directory, the prompts directory in use |
| `__MAX_ISSUES__` | `tracks.propose_max_issues` |
| `__PROPOSED_CHANGE__` | the change name this run writes (`propose` only) |
| `__FOCUS_HINT__` | the sentence `--focus` resolves to (`propose` only) |

The category playbooks are read raw by the subagents and carry no
placeholders; the top-level prompt tells each subagent which repo and state
directory it is working with.

`tracks.prompts_dir` points at a directory that **replaces** the built-in one
(relative to the planning root unless absolute): the runner reads
`<prompts_dir>/<phase>.md` and passes `<prompts_dir>` as `__PROMPTS_DIR__`, so
all four phase files and the `categories/` tree the prompts reference have to
be there. Copy the shipped set and edit.

## `--dry-run`

`abk track PHASE --dry-run` skips the usage check and every pull, and for
each eligible repo prints the first 40 lines of each rendered prompt and the
`claude` command with the prompt elided. Repo eligibility (`forge.check_access`)
is still checked.

## Budgets

No phase carries a dollar budget. The usage window is the real limit — a
guessed dollar ceiling drifts from actual cost, and set too low it refuses to
start a run rather than bounding one. `has_headroom` at the start of every
track is what keeps a timer from spending into credits: it checks the same
session/weekly usage-window percentages, against the same ramped thresholds
(each window's `..._usage_pause_pct` under `runtimes.claude_code`, rising to its
`..._pause_ceiling_pct` near its reset when one is set) the unit pipeline uses to decide whether a new unit may start, and
skips the whole run — before any repo, before any phase — if there's no
headroom.

## The systemd templates

`abk install-timers` renders the units from `templates/systemd/`, with the
planning directory filled in and the installation's name in every unit's name
(`abk-<planning dir>-tick.service`), so several installations can share a
machine. Each service is `Type=oneshot`, runs in the planning directory with a
PATH carrying `uv` and a node install (the OpenSpec CLI runs through `npx`, and
a user unit starts with no login environment), and execs `uv run abk
<command>`:

| Units | Runs | Timer |
|---|---|---|
| `abk-<name>-tick.service/.timer` | `abk tick` | 2 min after boot, then every 5 min, ±30 s |
| `abk-<name>-track-health.service/.timer` | `abk track health` | daily at 06:47, ±10 min, persistent |
| `abk-<name>-track-improve.service/.timer` | `abk track improve` | Sundays 09:00, ±20 min, persistent |
| `abk-<name>-track-recommend.service/.timer` | `abk track recommend` | Wednesdays 07:23, ±20 min, persistent |

`Persistent=true` runs a missed scheduled track on the next boot instead of
skipping it; the two weekly tracks are on different days so they never compete
for the usage window. One command installs and enables all of them:

```bash
abk install-timers
```

Running it again changes nothing if nothing has moved on, and heals what has:
it removes this installation's units that the current version no longer
installs. `abk doctor` reports the same things — installed but not enabled,
out of date, left over — so a fix is one command away. `--remove` takes the
installation's units off the machine. See [cli.md](cli.md#abk-install-timers---no-enable---remove---dry-run).

**The units run whatever the kit's checkout holds.** The planning repo installs
the kit as an editable path dependency, so `uv run abk` executes the files in
that directory as they are now: the branch checked out there, uncommitted edits
included. A timer firing while the checkout is mid-change runs the change.
