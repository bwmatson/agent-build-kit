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

One pass of the loop, the command the timer runs every few minutes. In
order: exit silently if nothing needs a tick (no unit `planned`/`running`/
`in_review` and every change planned in its current form); stop if paused;
read the usage windows and pause if either is past the threshold that applies
to it now (`usage_pause_pct` in the `session` / `weekly` section of
`runtimes.claude_code.limits`, rising towards its `usage_pause_ceiling_pct` as that
window's reset nears, when one is set) or unknown; `git fetch --prune origin` in every repo; poll each repo's host; convert units in
flight onto threads (only a unit with none); plan changes whose `tasks.md` changed; apply
`Needs:` lines; verify and archive fully merged changes; then resume the units a killed
run or a usage pause left `running` from their threads and build the ready
units, up to `limits.max_concurrent_stacks` at once. No unit that has never
started does while the units in progress across all repos are at
`limits.max_units_in_progress`, and a pass starts no more than fit under it;
the tick log and `abk status` then say "queue is full: N units in progress,
limit M" followed by the count in each state. Free slots
go to open-PR work first (reworks, restacks), then resuming builds, then new
units.

The pass keeps building until nothing is in flight and nothing is ready. Every
build that finishes is followed by another fetch, another poll and a fresh
readiness check, so what it unblocked — a child whose parent is now in
review, a dependent whose dependency merged — starts in the same pass. A pass
can therefore run for hours. Planning, converting, verifying and archiving
happen only at its start. A poll event for a unit whose build is still running
is left for a later poll rather than acted on mid-build. A unit is started at
most once per pass: one this pass already built that a review sends back
mid-pass waits for the next pass, while one requeued before this pass reached
it is built in this one.

- `--dry-run` runs everything up to the build and reports what is ready
  without building.
- `--only UNIT` (repeatable) builds only those units if ready, at every
  readiness check of the pass; polling, planning and archiving still happen.
  For pushing one unit through when usage is tight.

A build that pauses (the usage window spent, or rate limited) stops new
builds from starting; builds already in flight are still awaited before the
pass ends.

Exit 0, including when paused or idle. A tick is idle unless a unit is
planned, running or in review, a change's tasks are unplanned, or a change with
a satisfied unit is ready to archive and not yet verified (a failed
verification is kept, so it does not keep ticks busy). Exit 1 when a repo about to be built
has no repo-local `user.email` (agent commits would fall back to the machine's
global identity) — which can come mid-pass, after other units have already
been built, since each readiness check can reach a new repo. A unit that fails
is recorded `failed`, not an exit status.

### `abk status`

Prints whether the pipeline is paused (until when, why), the usage reading
(session %, weekly %, source), the count of units by state, and each
`in_review` unit with its PR. A `no recorded cause:` line lists the units that are `held`
or `planned` with work on them and no cause on their last history entry (a store from
before causes were kept); requeue each with `abk requeue`, or for a reviewer's hold hold
it again from the pull request. Changes nothing. Exit 0.

### `abk graph`

Rewrites `planning.graph_page` from `runs/units.json`. The tick does this on
every store write; this is for a page that went missing. Exit 0.

### `abk report [--by GROUPING] [--since DATE] [--change CHANGE] [--unit UNIT] [--include-estimates] [--json]`

Tokens by kind, cost and time by bucket (agent, checks, slot wait, usage-pause wait,
review wait) from the usage ledger and the unit store, grouped `--by` unit (default),
change, node, role, model, repo or day. `--since` (a date) keeps calls on or after it;
`--change` and `--unit` narrow to one. Estimated figures sit in their own columns and
stay out of the totals unless `--include-estimates`; a figure never recorded prints as
`-`, never `0`. The source column says whether figures were `reported`, from the
`gateway`, `estimated` or `none`, and flags a row whose gateway and agent-reported
figures differ by more than 10%. `--json` prints the same rows, with the difference.
A change archived by the pipeline is read from its per-unit summary, so its totals do
not change, but its nodes, roles and models read as `(summary)`, and its figures
are dated by the unit's last call, so `--by day` and `--since` place them all on that
day. Exit 0.

The same figures are written to `planning.usage_page` on every store write.

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
`[acceptance]` present (as `tier2`, after everything it exercises) or opted
out with a reasoned `Acceptance: none — ...` line. Prints each problem with
its line, then the groups when clean. Exit 1 if any change has a problem or
no `tasks.md`.

### `abk check`

`openspec validate --all --strict --json` in the planning repo. Prints
OpenSpec's output; exit code is OpenSpec's.

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
containing `--repo`, else `python-uv`. Prints each problem prefixed `✗`; exit
1 if any, else 0 with `✓ tests-first: ...`.

### `abk requeue UNIT [--restart | --rework]`

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

Any other state is refused: a running unit would be built twice, an in-review
one has a pull request that would be orphaned, and a planned or merged one has
nothing to retry. `--rework` and `--restart` cannot be combined. `--restart` does not touch the unit's branch or worktree; if
those came from a wrong base, remove them first (`git worktree remove`, then
`git branch -D`, after checking nothing on it is unpushed). Exit 2 for an
unknown unit, 1 when the unit is not stuck, else 0.

## Setting up

### `abk init [PLANNING_DIR] [--repo PATH ...] [--consumes REPO:CONSUMED[,CONSUMED] ...] [--yes] [--skip-research] [--skip-propose] [--force] [--update-rules] [--dry-run] [--register-store ID]`

Creates a planning repo for a set of checkouts; the one command that creates
an installation rather than reading one. Step by step in [init.md](init.md).

- `PLANNING_DIR` defaults to `.`.
- `--repo PATH` (repeatable) names a checkout; with none and without `--yes`,
  paths are prompted for one per line.
- `--consumes app:platform` overrides what a repo consumes (detected from its
  dependency references otherwise).
- `--yes` skips the prompt. `--skip-research` / `--skip-propose` skip the
  model-driven steps. `--force` overwrites `abk.yaml`, `openspec/config.yaml`,
  the recommendation documents and the generated changes. `--dry-run` prints
  the `abk.yaml` that would be written and the plan, and stops.
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
- Last, it asks the selected runtime (`runtime`, or `ABK_RUNTIME`) whether it
  refuses every command class abk forbids, and prints any it does not. When
  `runtimes.<name>.policy_fix` is set it asks before running that command
  from the planning repo, runs it only on a yes, and checks again afterwards;
  a no changes nothing and names what is still unenforced. With `--yes` the
  fix is only printed, never run. The answer is reused for 15 minutes
  (`<state_dir>/policy-check.json`). When the runtime raises instead of
  answering, init prints the error, caches nothing and carries on; `abk
  doctor` asks again.

Exit 2 when a repo path is not a directory, two repos share a name, or
`--consumes` names an unknown repo; 1 when the layout fails (git or
`openspec init`) or a generated change did not validate after its repair
round (its files are left to finish by hand); 0 otherwise.

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
| timers | | the units are installed but a timer is not enabled, or one is missing, out of date, or left over from an earlier version (each named). A note when none are installed — something else may run `abk tick` — or when `systemctl` cannot be asked |
| stale timer units | | a unit this framework wrote, for any installation, points at a directory that no longer exists. Nobody is left to remove it, and `systemctl enable` accepted it without complaint |
| node, openspec | `node`/`npx` are not on PATH, or the OpenSpec CLI does not run | |
| runtime | the selected runtime is not implemented, or its agent command (`runtimes.<name>.command`, else the adapter's own, `claude` for `claude_code`; the one every run spawns) is not on PATH | |
| runtime coverage | | the runtime's `policy_coverage` is short of `all_calls` |
| runtime policy | the runtime does not refuse a forbidden command class (each is named; the fix printed is `runtimes.<name>.policy_fix`, else the runtime's own advice). Reused for 15 minutes from `<state_dir>/policy-check.json`. Also when the check itself could not run: the runtime raised (e.g. its usage window is spent). Nothing is cached, so the next run asks again | not checked, because the agent command does not resolve (see the `runtime` check) |
| ssh key `<name>` | `deploy.ssh_key` does not exist | |
| verify.env `<VAR>` | the provider cannot resolve (names only; never values) | |
| rules | | The `# abk-rules: vN` stamp in `openspec/config.yaml` against the framework's rules version: a note when it is unstamped, a warning when the framework has added rules since (they are listed) or the stamp is newer. Wording is never compared. |
| abk.yaml `<name>` | | a service directory with no deploy rule, a rule prefix that no longer exists, a dev-stack script without `dev_stack`, a `live_written` path that is not a directory |
| skills `<target>` | | an installed abk skill is older than the framework |
| `<repo> <tool> version` | | a tool in `pyproject.toml`'s dependency groups is also run from a hook repository with its own `rev` in `.pre-commit-config.yaml`, so two versions can disagree. Only checked for repos with both files |
| `<repo> <tool> hook` | | a `repo: local`, `language: system` hook runs `uv run <tool>` for a tool absent from the dependency groups, so it fails. Only checked for repos with both files |
| telemetry traces / telemetry metrics | | `ABK_OTEL_ENABLED` is set and the signal has no endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`, or the per-signal one), or the endpoint does not answer. Only checked when enabled |

### `abk config [--show | --path]`

`--show` (the default) prints the effective configuration as YAML with every
default filled in; `--path` prints the `abk.yaml` in force. Exit 0.

### `abk changelog check [PATH]`

Checks a changelog's form: no conflict marker, a blank line between bullets, no bullet
repeated, every bullet under a `##` section, headings in order. Each problem prints as
`path line N: message`, and the exit is 1 when there are any. With no `PATH` it reads the
file named by the `changelog` setting of the repo the current directory belongs to (a
worktree included). A missing file passes with a note; so does a repo with the setting
`null`. Tier 1 runs it for every repo with the setting on.

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
