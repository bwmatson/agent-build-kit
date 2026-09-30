# The scheduled tracks

Beside the unit pipeline, four **tracks** keep watch on the repos: `health`,
`improve`, `recommend`, and the `implement` pass the first three hand off
to. Each is a Claude Code run against one repo with a Markdown mission
prompt; `abk track PHASE` runs one now, and `abk install-timers` writes systemd timers
for the three scheduled ones.

| Track | Cadence | Reads | Writes |
|---|---|---|---|
| `health` | daily | logs, resources, LLM observability, pipeline state, secrets — "is something actually wrong right now" | a run log with a `**Status:**` line; `implement` straight away on `ATTENTION`/`URGENT` |
| `improve` | weekly | lint and types, dependency staleness, README drift, convention adherence — "this could be better" | a run log; then `implement` |
| `recommend` | weekly, another day | test coverage gaps, technical debt, architecture opportunities (the one with web access), cost/performance — bigger-picture, mostly for a human | a run log; then `implement` for the rare bounded finding |
| `implement` | after the above, or on demand | the run logs' "Actionable candidates" and `tracked-issues.md` | up to `tracks.implement_max_prs` PRs, in a fresh worktree; never merges |

## The per-repo flow

`run_track` (`tracks/runner.py`):

1. **Headroom.** The usage guard's `may_start_unit` decides; with none the run
   logs why and exits 0. The next timer is the retry — a daily track does not
   schedule its own resume the way a five-minute tick does.
2. **Pull the planning repo** to its default branch (`git checkout`, `git
   pull --ff-only origin`), since every phase writes and pushes its run log
   there. `planning.self_pull: false` skips this. A failed pull is fatal.
3. **Eligible repos**: each `abk.yaml` repo (or only `--project NAME`) whose
   checkout is a git repo, whose `origin` is a remote some forge recognises,
   matching its
   `slug`, and which `gh repo view` can see. Anything else is logged and
   skipped, so a repo can be listed before it exists on its host.
4. Per repo, in `abk.yaml` order: pull its default branch (a failure skips
   the repo and counts as failed), then dispatch:
   - `health`: one phase, no worktree. Afterwards the run log's `**Status:**
     OK | PENDING RESOLUTION | ATTENTION | URGENT` line is read back;
     `ATTENTION` or `URGENT` — a genuinely new finding, not one already
     pending a PR — runs `implement` for the same repo now. A missing or
     unparseable status means "can't tell", and nothing more happens.
   - `improve`, `recommend`: the discovery phase, then `implement` — always,
     even when discovery exited non-zero; implement falls back to the
     candidates the run logs already hold.
   - `implement`: one phase in a fresh `claude --worktree abk-<run id>`.

No phase carries a dollar budget — every one of them is bounded the same way
as the headroom check in step 1: the usage window is the limit, read live.
A guessed dollar ceiling beside that drifts from real cost, and set too low
it refuses to start a run instead of bounding one.

Exit 1 if any repo's phase exited non-zero; a non-zero exit is never fatal to
the next phase or repo.

Each phase is one `claude -p` call, run with the repo's checkout as the
working directory:

```
claude -p [--worktree abk-<run id>] --add-dir <planning root>
  --permission-mode acceptEdits
  --allowedTools "<tracks.allowed_tools>" --disallowedTools "<tracks.disallowed_tools>"
  --model <tracks.model> --output-format json <prompt>
```

The raw JSON goes to `<planning root>/<tracks.raw_output_dir>/<run id>-<repo>-<phase>.json`
(`.last-runs/`, gitignored). What a track agent may run is the tool
allow/deny lists in `abk.yaml`, which deny force pushes, hard resets,
recursive deletes, branch force-deletes, and every forge's way of merging a
pull request — plus a policy hook that refuses creating or switching a branch,
a reset, a forced branch move and a cherry-pick aimed at the planning repo
(the pipeline commits there). The same git aimed at the code repo's worktree
is allowed.

## Run logs and the tracker

Every phase writes a run log at `<state_dir>/<run id>-<repo>-<track>.md`
(`runs/20260101-064700-app-health.md`, say), where the run id is the process
start time. The path is injected into the prompt, not left for the agent to
invent: health's status readback depends on it being predictable.

The prompts share a shape. Each phase first refreshes
`<state_dir>/tracked-issues.md` — the workspace-wide list of findings with a
PR open ("Pending resolution") or declined ("Rejected"), checked against each
PR's real state with `gh pr view` — then checks whether the previous run's
`[not-yet-actioned]` candidates were fixed by hand since (marking them
`[actioned — commit <hash>]`), fans the category playbooks out to subagents,
cross-references findings against the tracker so a problem with a PR already
open is not proposed again, and writes the log with an "Actionable
candidates for the next implement run" section. `implement` reads those
sections most recent first, groups candidates by underlying issue, picks up
to `implement_max_prs` distinct, well-evidenced, bounded ones, opens a PR
each with a unit test, adds a "Pending resolution" entry per PR, and marks
the source candidate `[actioned — PR #N]`. After every phase the runner — not the agent — commits what was written
under the state directory (the run log and tracker edits) to the planning
repo's default branch and pushes. A push the remote rejected is retried once
after a fast-forward; a second rejection is logged and the commit is kept. If
the agent left the planning repo on another branch, the runner checks the
default branch out again, keeps the stray branch, and logs its name; if the
default branch was rewritten, the run stops and nothing is committed. A tick
also checks the default branch out, and logs the branch it found, before it
reads state.

`--focus` on `implement` biases which entries are read first: a track name
resolves to that track's most recent run log for the repo; a run-id prefix
resolves to the matching log (preferring the source track's over the run's
own `-implement.md`). Neither changes what qualifies.

## Prompts and placeholders

The prompts are package data under `tracks/prompts/`: `health.md`,
`improve.md`, `recommend.md`, `implement.md`, and `categories/<track>/*.md`
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
| `__IMPLEMENT_MAX_PRS__` | `tracks.implement_max_prs` |
| `__FOCUS_HINT__` | the sentence `--focus` resolves to (implement only) |

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
`claude` command with the prompt elided. Repo eligibility (`gh repo view`)
is still checked.

## Budgets

No phase carries a dollar budget. The usage window is the real limit — a
guessed dollar ceiling drifts from actual cost, and set too low it refuses to
start a run rather than bounding one. `has_headroom` at the start of every
track is what keeps a timer from spending into credits: it checks the same
session/weekly usage-window percentages, against the same ramped thresholds
(`limits.usage_pause_pct` rising to `usage_ceiling_pct` near each window's
reset) the unit pipeline uses to decide whether a new unit may start, and
skips the whole run — before any repo, before any phase — if there's no
headroom.

## The systemd templates

`abk install-timers` renders the units from `templates/systemd/`, with the planning
directory filled in. Each service is `Type=oneshot`, runs in the planning
directory with a PATH carrying `uv` and a node install (the OpenSpec CLI
runs through `npx`, and a user unit starts with no login environment), and
execs `uv run abk <command>`:

| Units | Runs | Timer |
|---|---|---|
| `abk-tick.service/.timer` | `abk tick` | 2 min after boot, then every 5 min, ±30 s |
| `abk-track-health.service/.timer` | `abk track health` | daily at 06:47, ±10 min, persistent |
| `abk-track-improve.service/.timer` | `abk track improve` | Sundays 09:00, ±20 min, persistent |
| `abk-track-recommend.service/.timer` | `abk track recommend` | Wednesdays 07:23, ±20 min, persistent |

`Persistent=true` runs a missed scheduled track on the next boot instead of
skipping it; the two weekly tracks are on different days so they never
compete for the usage window. Install for the user manager:

```bash
abk install-timers
```

and the same for each `abk-track-*` pair.
