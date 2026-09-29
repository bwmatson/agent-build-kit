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
to it now (`limits.usage_pause_pct`, rising towards `usage_ceiling_pct` as
that window's reset nears) or unknown; `git fetch --prune origin` in every repo; poll GitHub; reclaim units
left `running` by a dead process; plan changes whose `tasks.md` changed; apply
`Needs:` lines; verify and archive fully merged changes; then build every
ready unit in parallel.

- `--dry-run` runs everything up to the build and reports what is ready
  without building.
- `--only UNIT` (repeatable) builds only those units if ready; polling,
  planning and archiving still happen. For pushing one unit through when
  usage is tight.

Exit 0, including when paused or idle. Exit 1 when a repo about to be built
has no repo-local `user.email` (agent commits would fall back to the machine's
global identity). A unit that fails is recorded `failed`, not an exit status.

### `abk status`

Prints whether the pipeline is paused (until when, why), the usage reading
(session %, weekly %, source), the count of units by state, and each
`in_review` unit with its PR. Changes nothing. Exit 0.

### `abk graph`

Rewrites `planning.graph_page` from `runs/units.json`. The tick does this on
every store write; this is for a page that went missing. Exit 0.

### `abk verify CHANGE`

Verifies one change by hand — after fixing what made the automatic
verification fail — and archives it if it passes. Deploys what the change's
merged PRs touched (`deploy.rules`), runs the live tests they added, records
the outcome in `runs/verified.json`. Exit 1 with the detail when it fails, 0
when it passes (printing what was deployed and what was archived).

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
directory, against `main`): commits read as tests-then-implementation, lint
and format pass at each tests commit with type checking skipped, and the new
tests there fail for an accepted reason. `--cache` keeps results by patch-id
across restacks. `--profile` defaults to the profile `abk.yaml` gives the repo
containing `--repo`, else `python-uv`. Prints each problem prefixed `✗`; exit
1 if any, else 0 with `✓ tests-first: ...`.

## Setting up

### `abk init [PLANNING_DIR] [--repo PATH ...] [--consumes REPO:CONSUMED[,CONSUMED] ...] [--yes] [--skip-research] [--skip-propose] [--force] [--dry-run] [--register-store ID]`

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
- `--register-store ID` runs `openspec store register --id ID --yes` on the
  planning repo.
- Last, it asks the selected runtime (`runtime`, or `ABK_RUNTIME`) whether it
  refuses every command class abk forbids, and prints any it does not. When
  `runtimes.<name>.policy_fix` is set it asks before running that command
  from the planning repo, runs it only on a yes, and checks again afterwards;
  a no changes nothing and names what is still unenforced. With `--yes` the
  fix is only printed, never run. The answer is reused for 15 minutes
  (`runs/policy-check.json`).

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

### `abk doctor`

Is this installation in a state the pipeline can run in? Each check prints
`ok`, `warn` or `FAIL` with a one-line fix; exit 1 if anything failed, else 0.

| Check | FAIL when | warn when |
|---|---|---|
| config | `abk.yaml` is missing, malformed or has an unknown key | |
| worktree root | `planning.worktree_root` is inside the planning repo | |
| repo `<name>` | the path is missing, not a git checkout, or has no repo-local `user.email` | |
| gh `<owner>` | `gh auth token --user <owner>` yields nothing for an owner in `repos` | |
| node, openspec | `node`/`npx` are not on PATH, or the OpenSpec CLI does not run | |
| runtime | the selected runtime is not implemented, or its agent command (`runtimes.<name>.command`, else the adapter's own, `claude` for `claude_code`) is not on PATH | |
| runtime coverage | | the runtime's `policy_coverage` is short of `all_calls` |
| runtime policy | the runtime does not refuse a forbidden command class (each is named; the fix printed is `runtimes.<name>.policy_fix`). Reused for 15 minutes from `runs/policy-check.json` | |
| ssh key `<name>` | `deploy.ssh_key` does not exist | |
| verify.env `<VAR>` | the provider cannot resolve (names only; never values) | |
| rules | | The `# abk-rules: vN` stamp in `openspec/config.yaml` against the framework's rules version: a note when it is unstamped, a warning when the framework has added rules since (they are listed) or the stamp is newer. Wording is never compared. |
| abk.yaml `<name>` | | a service directory with no deploy rule, a rule prefix that no longer exists, a dev-stack script without `dev_stack`, a `live_written` path that is not a directory |
| skills `<target>` | | an installed abk skill is older than the framework |

### `abk config [--show | --path]`

`--show` (the default) prints the effective configuration as YAML with every
default filled in; `--path` prints the `abk.yaml` in force. Exit 0.

### `abk scrub-check --target DIR [--show-terms]`

Run *from an installation*, greps `DIR` (a framework checkout) for anything
that names this installation. The terms are derived from `abk.yaml` each
time — the planning directory name, repo names, GitHub owners and project
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
then an implement pass), `recommend` (weekly bigger-picture discovery then an
implement pass) or `implement` (work down the existing backlog; `--focus`
says which run-log entries to read first). `--dry-run` prints each rendered
prompt's opening lines and the `claude` command without the usage check, the
pulls, or running anything. Details in [tracks.md](tracks.md). Exit 1 if any
repo's phase exited non-zero or could not be pulled, else 0 — including when
there was no headroom or no eligible repo.
