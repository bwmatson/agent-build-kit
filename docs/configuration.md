# Configuration

Three files configure an installation, and they answer different questions. The rule that
keeps them apart: **`abk.yaml` reads the same on every machine that runs the pipeline.**

- **`abk.yaml`**, in the planning repo, committed and reviewed: everything that describes
  *this workspace* and is true wherever it runs — which repos, which host each lives on,
  how each deploys and tests, what the planner should know about how they relate, the
  models and the team's policy limits. The schema is strict (`extra="forbid"`): a
  misspelled key fails at load, not later.
- **`abk.local.yaml`**, beside it, ignored by git, merged over it key by key: everything that
  differs *per machine or per person* — where a repo is checked out, which Claude account
  builds what, the usage thresholds of a person's plan, what a machine can run.
- **`.env`**, in the planning repo, ignored by git: secrets and single per-machine values —
  a token, a worktree root override, a model override, the OpenSpec version pin.

**Installation facts live here.** The framework knows nothing about any
particular installation; a fact that belongs to one (a path, an owner, a
deploy command, a credential name) is a field in `abk.yaml` with a default,
never a constant in code, a prompt or a skill.

## Which file holds what

Ask of any line: *would this be wrong on another person's machine?* If it would, it is local.

| Setting | File | Why |
|---|---|---|
| Repo names, slugs, forges, default branches, `profile`, `languages`, `projects`, deploy rules, `consumes`, `relationships` | `abk.yaml` | describes the workspace |
| Test kinds and markers, `e2e_splits` and `e2e_dimensions` declarations, `e2e_unit_scope` | `abk.yaml` | the same tests run wherever the code does |
| Models, review settings, `global_limits` and the defaults that are safe everywhere | `abk.yaml` | one behaviour for everyone |
| `project_limits` (`max_concurrent_stacks`, `max_units_in_progress`) | `abk.local.yaml` | how many units this machine can run at once |
| `repos.<name>.path` (a checkout), `planning.worktree_root` | `abk.local.yaml` | a path on one disk |
| `verify.env.<NAME>.file` (where a settings file sits) | `abk.local.yaml` | a path on one disk; the entry and its `path` stay in `abk.yaml` |
| `repos.<name>.account` (which Claude account builds a repo) | `abk.local.yaml` | depends on who runs the pipeline and which accounts they have; a person with one account sets nothing |
| `runtimes.claude_code.accounts.<label>`: `config_dir`, `limits`, `max_units_in_progress` | `abk.local.yaml` | a directory and a plan's allowances |
| `runtimes.claude_code.limits` (the default account's usage thresholds) and `usage_cache_*` | `abk.local.yaml` | a plan's allowances differ per person |
| `runtimes.<name>.models` (which model does which role) | `abk.yaml` | a model alias is that runtime's own name and describes the workspace |
| `runtimes.<name>.command` and `policy_fix`, where the program is an absolute path | `abk.local.yaml` or `.env` | where a program sits differs per machine; a bare program name on the PATH is fine in `abk.yaml` |
| `tests.e2e_available`, a split's `hold`, `tests.e2e_schedule: "off"` for a machine | `abk.local.yaml` | what this machine can run or should spend |
| Tokens, PATs, `GH_TOKEN`, `ABK_*` switches, a worktree root | `.env` | secrets and per-machine values, read through `from: env-file` |

How they combine: `abk.local.yaml` is merged over `abk.yaml` when the configuration loads;
mappings merge by key, and a list, a string or `null` replaces the committed value whole. A
`config_dir` in the committed file is refused. `abk config --path` prints the files in force
and `abk config --show` the merged result. `abk doctor`'s `public content` check warns when
a committed `abk.yaml` holds a path outside the checkout or a home directory. A committed file
that needs a value from a machine reads it through the overlay or an `env-file` entry, never a
path written into it; "Where an installation's facts live" below has the details.

## Locating `abk.yaml`

In order: `abk --config PATH`, then `ABK_CONFIG` in the environment, then the
nearest `abk.yaml` walking up from the working directory. The file's
directory is the **planning root**; every relative path in the file is
relative to it. Commands that need an installation exit 2 when none is found.

`abk config --path` prints the file in force; `abk config --show` (the
default) prints the effective configuration with every default filled in.
`abk doctor` checks the installation is runnable — see [cli.md](cli.md). One of its checks
reports each repo's agent commands:

| Check | Status | Meaning |
|---|---|---|
| agent commands `<repo>` | ok | the number of effective commands, all allowed by the build allow-list |
| agent commands `<repo>` | info | none named: the profile gives none and `agent_commands` is not set |
| agent commands `<repo>` | FAIL | a command (a profile's own, which is not a load error) is outside the allow-list; allow it in the profile or set `repos.<name>.agent_commands` |
| agent commands `<repo>` | warn | the commands would not all fit the 600-character prompt section; the leading ones are listed |

`abk.yaml` should read the same on every machine; settings that belong to a machine or a
person go in the ignored `abk.local.yaml`. `abk doctor` reads the committed file alone
and, under "machine keys", **warns** for `repos.<name>.account`, `project_limits`,
`runtimes.<name>.accounts`, `tests.e2e_available` and a runtime `command` or `policy_fix`
that starts with an absolute path. It only **notes** `runtimes.<name>.limits`, a split
`hold` and `tests.e2e_schedule: "off"`, which a team may commit as defaults. It says
nothing about `runtimes.<name>.models`, or about the same keys in `abk.local.yaml`.

`abk config --migrate` moves the machine settings of a tracked `abk.yaml` to `abk.local.yaml`:
everything the check warns about. The defaults it only notes stay unless you add
`--include-defaults`, which moves `runtimes.<name>.limits`, a split `hold` and
`tests.e2e_schedule: "off"` too. The merged configuration does not change.

## `abk.yaml` reference

Every field, with its default. A key at its default can be left out;
`abk init` writes only what differs from the defaults.

```yaml
version: 1

planning:
  state_dir: runs               # pipeline state, run logs, each e2e-test run's full
                                # output (e2e-output/) and the usage ledger
                                # (usage-ledger.jsonl and decisions.jsonl, both
                                # gitignored; add a line for each if you move
                                # state_dir; docs/architecture.md).
                                # Relative to the planning root unless absolute.
  specs_dir: openspec           # the OpenSpec store; changes are read from
                                # <specs_dir>/changes/*/tasks.md.
  graph_page: docs/unit_graph.md
                                # the mermaid unit graph, rewritten on every
                                # state change.
  usage_page: docs/unit_cost.md
                                # per-change totals and the most expensive units
                                # from the usage ledger, rewritten on every store
                                # write; a failed write is reported, never fatal.
  worktree_root: null           # where per-unit worktrees are checked out:
                                # <root>/<repo dir name>/<branch>. Never inside
                                # the planning repo (refused at load). null =
                                # ~/.local/share/<planning dir name>/worktrees.
  self_pull: true               # the tracks pull a separate planning repo, and a
                                # tick or track syncs a pipeline worktree, before
                                # running.
  publish: direct               # direct | branch. In a pipeline worktree, where the
                                # tracks' planning commits go: pushed to the default
                                # branch, or to planning/<run>-<project>-<phase> with
                                # a pull request. No effect elsewhere.

openspec:
  command: null                 # argv for the OpenSpec CLI. null = npx --yes
                                # @fission-ai/openspec@<ABK_OPENSPEC_VERSION>.

retention:
  decision_log_mb: 50           # decisions.jsonl and admissions.jsonl are each trimmed to this
                                # size, newest lines kept
  unit_log_days: 30             # a unit's run log older than this goes once its summary
                                # is in the usage ledger; one without a summary stays

git:
  push_host: ""                 # an ssh host alias (from ~/.ssh/config)
                                # carrying the key agent branches are pushed
                                # as; origin's ssh URL is rewritten to it. "" =
                                # push to origin as whoever owns the default
                                # key. Ignored for https remotes.
  branch_prefix: spec/          # marks a branch and its PR as agent-owned:
                                # units are <prefix><change>/<n>, the poller
                                # ignores everything else, and force-with-lease
                                # is permitted only under it.

runtime: claude_code            # what executes every build/review/rework step,
                                # for the whole workspace. The registry in
                                # agent_build_kit.runtimes names the choices —
                                # see agent-runtimes.md. ABK_RUNTIME overrides
                                # it per machine, for trying one out without
                                # moving every repo at once.

runtimes:                       # one entry per runtime that needs a fact abk
                                # cannot default, and only for the runtimes
                                # this workspace uses. An unknown `runtime`, or
                                # one missing a fact its adapter requires,
                                # fails at load; only the selected runtime's
                                # entry is checked.
  claude_code:                  # the Claude subscription: a five-hour session
    models:                     # bare aliases, not pinned ids: this runtime's own
                                # names for the roles. A role left out takes the
                                # runtime's own default (these, on claude_code);
                                # ABK_*_MODEL overrides win over both. A second
                                # runtime names its own models under its own entry
      implement: sonnet         # the tests, implementation and check-fix runs
      rework: sonnet            # reworks, restack conflict resolution, adapt, when they
                                # start a new session; a continued build session
                                # keeps its model
      review: opus              # the first review of a fresh build
      rework_review: opus       # every review of a rework. Both reviews default
                                # to a different model from the author's; if the
                                # author is set to opus, set this to another
    context_windows: {}         # model id or alias -> window in tokens, for when the
                                # result does not name it (read by this runtime only;
                                # an acp agent says its own window); recorded as an
                                # estimate
    limits:                     # and a seven-day week fill independently, so
      session:                  # each has its own section, with the same names
        usage_pause_pct: 70     # % of the window at which no new unit starts,
                                # for most of it
        usage_pause_ceiling_pct:  # what that rises to at the window's reset.
                                  # Unset = usage_pause_pct: no ramp. Below 100,
                                  # where credits start paying
        usage_relief_fraction: 0.25  # the trailing part of the window the rise
                                     # is spread over (a session's last ~75
                                     # minutes, a week's last ~42 hours).
                                     # Unused when there is no ramp
        usage_resume_buffer_pct: 5   # room above current usage the threshold
                                     # must offer before a pause lifts
        usage_unit_allowance_pct: auto  # points of this window one unit may spend,
                                      # counted per unit when a start is allowed on
                                      # an estimate. `auto` calibrates it from the recorded
                                      # history (fallback 10 for the session, 2 for the week,
                                      # ceiling twice that); a whole number is the fallback
                                      # and the cap on the calibrated figure
        usage_allowance_floor_pct: 1  # the least a calibrated allowance may be
        usage_estimate_basis: cost    # cost (recorded cost times a learned points per dollar,
                                      # where adopted) or units (the flat per-unit figure)
        usage_estimate_intercept: true  # a points-per-hour term in the cost fit; on for the session
      weekly:                   # the same settings, for the week
        usage_pause_pct: 70
        usage_pause_ceiling_pct:
        usage_relief_fraction: 0.25
        usage_resume_buffer_pct: 5
        usage_unit_allowance_pct: auto  # as above
        usage_allowance_floor_pct: 1
        usage_estimate_basis: cost      # as above
        usage_estimate_intercept: false  # as above, off for the weekly
      calibrate_usage_allowances: true  # false: every window uses its configured allowance
      usage_allowance_quantile: 0.9     # the quantile of points gained per unit (above 0, at most 1)
      usage_allowance_window: 30        # newest usable pairs of readings it is taken over
      usage_allowance_min_pairs: 8      # fewer pairs than this and the configured allowance stands
      usage_cost_min_pairs: 8           # pairs with cost needed before the cost basis is fitted
      usage_cost_quantile: 0.9          # the quantile the cost fit's scale covers (above 0, at most 1)
      usage_forecast: true              # forecast a start from its review tier's recorded history; false decides on the reading and estimate alone
      usage_forecast_min_runs: 10       # units a tier needs before its own history is used (else the flat allowance, the prior)
      usage_forecast_quantile: 0.9      # the quantile the chance of each step is bounded at (above 0, at most 1)
      usage_stale_retry_minutes: 5  # how long a start is refused when the only
                                    # reading is too old to trust
      usage_cache_minutes: 15  # how long a good usage reading answers every reader (the shortest);
                               # one process refreshes it at expiry under a lock, the rest are
                               # served the last good reading
      usage_claude_cache_minutes: 15  # how fresh Claude Code's own usage block (~/.claude.json) must
                                      # be to decide a start with no call; follows usage_cache_minutes
                                      # when unset, 0 turns it off, never trusted past an hour
      usage_cache_max_minutes: 30  # the most refusals can stretch that to
      usage_fallback_minutes: 30  # how old the last good reading may be to cover a failed call
      usage_climb_floor: 0.2  # slowest climb, in points a minute, a window is assumed to make
      usage_climb_margin_pct: 2  # points added to what a reading could have gained since
      usage_headroom_margin_pct: 5  # room an estimate must leave under a threshold to allow a start
      usage_estimate_max_starts: 3  # units that may start on an estimate for one reading (0: none)
  # acp:                        # an agent speaking the Agent Client Protocol
  #   command: [some-agent, acp]          # how to spawn it
  #   policy_fix: [scripts/constrain.sh]  # what `abk init` offers to run when
  #                                       # the agent does not refuse what the
  #                                       # command policy forbids
  #   policy_extra: ["git * push --mirror*"]  # this installation's own command globs,
  #                                       # in the dialect `abk policy show` prints;
  #                                       # added after the kit's by
  #                                       # `abk policy patterns --extra`; none blank
  #   policy: unchecked                   # the only value: carried on without
  #                                       # confirming the agent refuses what
  #                                       # the command policy forbids
  #   models: {implement: "..."}          # this runtime's own model names

session_reuse:                  # per agent role, whether its nodes continue the
  build: true                   # role's latest session. build: the tests,
  review: false                 # implement, fix, rework, restack and adapt share
                                # one. review can only be false: a review always
                                # starts fresh. A role left out is off.

environment:                    # how the pipeline's own environment is kept
                                # current; absent = none is managed and
                                # `abk doctor` warns
  sync: [uv, sync]              # required, not empty: brings it up to date
  check: [uv, run, --no-sync, python, -c, "import agent_build_kit"]
                                # required, not empty: exits 0 when healthy
  inputs:                       # path patterns relative to the repository: `*`
                                # within one folder, `?`, `[...]`, `**` for any
                                # number of folders, a folder for every file
                                # under it. Absolute patterns, and `..` with a
                                # wildcard, are refused; a plain `..` path loads
                                # with a warning until the next release; to notice
                                # such a file drifting, use `check` (a command that
                                # fails when it has) instead
    dependencies: [pyproject.toml]   # e.g. "**/manifest.json" for nested modules
    lock: [uv.lock]             # also left out of a unit's size, matched by the
                                # pattern's file name wherever the file sits
    other: []                   # a pattern matching nothing is hashed as missing
                                # and `abk doctor` reports it. When every
                                # dependency and other input is missing the
                                # environment is pending: no `sync` and no
                                # `check` run (both would fail for want of
                                # them) until a file appears and the hash
                                # changes
  artifacts: [.venv]            # what `sync` and `check` produce, as patterns.
                                # Never an input or part of the hash, never
                                # counted as a leftover in a unit's worktree,
                                # never committed or discarded. A tracked file
                                # under one is ordinary work, and `abk doctor`
                                # warns. Default: none
# A repository entry under `repos` takes the same `environment` section, with
# paths relative to the repository. `abk doctor` warns for one without it.
# It runs in the unit's worktree: before the tests and every unit-test, `sync` runs
# when the inputs' hash differs from the one recorded for that worktree, then
# `check`. With inputs equal to the base branch's a failure is the environment's
# (cause `environment`); a failing `sync` or `check` after the unit changed an
# input is the unit's, and its output is the fix round's feedback.

context:
  compaction_drop_share: 0.3    # a fall in the context's fill between two requests
                                # larger than this share of the window counts as a
                                # compaction, for a runtime with no marker of its own
  warn_share: 0.8               # a step ending above this share of the window logs a
                                # warning (a signal only)

# Scheduling is set once for every project in `project_limits`; the rest of the
# workspace-wide settings are `global_limits`. There is no per-repo override of
# `project_limits`; a setting a repo needs of its own is a follow-on change, not a key.
# The old root name `limits` still loads as `global_limits` with a deprecation notice
# (both set is an error). A scheduling setting left in `global_limits` or `limits`
# fails the load; `abk config --migrate` moves it (see docs/cli.md).
project_limits:
  max_concurrent_stacks: 4      # units being built at once, in each project (every limit
                                # here is counted for each project, not across all repos)
  max_concurrent_restacks: 2    # moved-base runs (a branch moved onto a changed base, and
                                # the run after it) at once in each project; the lane's cap
                                # bounds the run, which counts toward slot occupancy but is
                                # never held back by max_concurrent_stacks
  max_units_in_progress: 5      # units started and not finished, in each project (once a
                                # Claude account is named: in each account, the default
                                # account's across all its projects), at
                                # least 1; at it no unit that has never started does,
                                # while reworks, resumes and finishing reviewed work
                                # still run; a blocked unit, and a failed unit that waits
                                # on another unit, do not count
  emergency_extra: 1            # the emergency lane's cap in each project: priority-0
                                # units that may start past the places and workers above;
                                # 0 turns the lane off

global_limits:
  stack_depth_build_cap: 3      # longest chain of in-review PRs from main a
                                # new unit may extend
  stack_depth_rebase_cap:       # deepest a dependent may sit when a merge
                                # restacks it; unset = the build cap's value
  max_flakes_per_run: 5         # more tests than this failing a run's first pass and passing
                                # alone is one recorded storm, no fix change per test
  checks_register_seconds: 120  # seconds after a push in which a pull request with no
                                # checks yet still reads `checking`
  wait_end_requeue: auto        # how a failed unit is requeued once when its wait ends:
                                # auto (default; the mode follows its record), resume,
                                # rework, or off (only a person requeues it)
  label_sweep_per_tick: 20      # finished units' pull requests whose stale state
                                # label a round takes off (each tick and each
                                # refresh of a pass), at least 1
  manual_check_seconds: 30      # seconds a manual step's check script may run, at
                                # least 1
  min_unit_lines: 400           # estimated changed lines before the planner
                                # stops absorbing the next task group
  calibrate_estimates: true     # multiply a unit's estimate by what units of
                                # its kind (repo, tier, group flag) landed at
                                # before holding it to the ceiling; off, plans
                                # are checked on the raw estimate
  calibration_window: 20        # the newest merged units of a kind sampled (>= 1)
  calibration_min: 3            # fewer samples than this: the ratio is 1
                                # (>= 1, not above the window)
  calibration_shrink: 5         # n samples carry n / (n + shrink) of the
                                # distance from 1 (>= 0; 0 uses the median whole)
  calibration_sample_clamp: [0.5, 4.0]
                                # each sample, actual over estimate, is held to
                                # this range (low in (0, 1], high >= 1)
  calibration_max: 3.0          # the ratio is kept between 1 and this (>= 1)
  calibration_examples: 3       # newest merged units of each listed kind shown
                                # to the planner (>= 0; 0 shows none)
  calibration_kinds_listed: 5   # kinds shown to the planner, most samples
                                # first (>= 1)
  generated_files: ["*.generated.ts", ...]
                                # path patterns (whole path or file name) left
                                # out of a unit's actual size, together with the
                                # lock files the environments name (above);
                                # none by default
  max_review_rounds: 3          # review rounds before a unit fails
  max_check_rounds: 3           # times a branch failing its checks (lint, types,
                                # tests) goes back to the builder before a
                                # reviewer is asked. Counted per round of
                                # review: it starts again before each one.
                                # null = no limit (a fix that changes nothing
                                # still ends the run); 0 = no fix attempt (the
                                # checks still run: they are the gate)
  max_adapt_rounds: 2           # adapt-step accounting asks, first included,
                                # before a unit fails
  max_plan_attempts: 3          # planner attempts per version of a tasks.md
  max_check_reruns: 2           # re-runs of a head commit's cancelled checks
                                # before the host is left cancelling them
  transcript_result_chars: 20000  # longest tool result a unit's transcript
                                  # keeps whole; longer ones are cut
  transcript_runs_kept: 3       # runs of one unit that keep their transcript
  # The earlier, numbered spellings of the next keys still load, with a notice, for one release.
  unit_test_command_seconds: 3600   # longest a unit-test command may run before it is aborted
  unit_test_abort_grace_seconds: 10  # how long an aborted command has to exit before it is killed
  unit_test_repeat_runs: 3          # times the tests a unit added or changed are run again under load (0: off)
  restack_check: affected           # unit-test after a clean move: scoped by the files the move brought in (affected) or the whole suite (full); a scoped move runs the unit's own tests and the profile's selection, and the profile selects only where `checks.affected` records data
  e2e_base_runs: 1                  # run the untouched failed e2e-test tests once on the base (0: off)
  e2e_unit_scope: own               # e2e-test per unit: only the tests it added or changed (own) or the whole marker (full); tests.e2e_unit_scope overrides per repo
  e2e_schedule: weekly              # whole e2e-test suite on the default branch: daily | weekly | monthly | 'off' (quote it); tests.e2e_schedule overrides per repo
  e2e_lock_wait_seconds: 5400       # longest post-merge verification waits for the e2e-test lock before reporting it busy
  e2e_durations_shown: 15           # slowest e2e-test test entries the posted result lists (0 = all)
  network_probe_timeout_seconds: 5  # longest the outage probe waits to connect to one host
  network_control_hosts: [one.one.one.one, dns.google]  # bare host names tried beside the code hosts to tell a network outage from a model service outage
  service_unavailable_attempts: 5   # times in a row a 5xx or 529 from the model service parks a unit before the next fails it

builders:
  installable_files: []         # base names (never paths or patterns) `abk install-config` may
                                # install besides `.pre-commit-config.yaml`
  stubbed_tdd_commits: true       # builders.stubbed_tdd_commits. true = build each task group as its own pair of commits (`test:`
                                # with stubs, then `feat:`), the stubs and tests checked for lint,
                                # format and types before the tests commit; only for a toolchain
                                # profile that supports stubs. Default on; set false to turn it off

tracks:                         # the scheduled tracks (docs/tracks.md); their
                                # model and tool lists stay here, not under
                                # runtimes.<name>
  model: sonnet                 # Claude Code's alias, sent to whichever
                                # runtime is active and not resolved per
                                # runtime: set it when selecting another
  propose_max_issues: 3         # issues one propose pass may write up as task
                                # groups in its change, per repo. The change is
                                # built by the pipeline, not by the track.
  allowed_tools: null           # Claude Code --allowedTools syntax; both
                                # lists have no effect under the acp runtime.
                                # null = the built-in list (read, edit, git,
                                # the toolchain, abk, and every forge's PR
                                # read commands); a list set here is used as is
  disallowed_tools: >-
    Bash(git push --force*) Bash(git reset --hard*) Bash(rm -rf*)
    Bash(git branch -D*) Bash(gh pr merge*)
  prompts_dir: null             # a directory replacing the built-in prompts
                                # (same file names); relative to the planning
                                # root unless absolute
  raw_output_dir: .last-runs    # each phase's raw `claude -p` events, relative
                                # to the planning root

repos:                          # ordered: deploy order is derived from
                                # `consumes`, and the planner sees them in
                                # this order. A task group's [repo] tag must
                                # be one of these keys, spelled exactly.
  platform:
    path: /srv/src/platform     # the checkout (~ is expanded); a path on one disk,
                                # so it belongs in abk.local.yaml
    slug: example/platform      # GitHub owner/name. The owner decides which
                                # `gh` account's token is used.
    default_branch: main        # the branch units are built on and their pull
                                # requests target when they stack on nothing,
                                # and one a direct push is refused to. `abk init`
                                # learns it from where the host says pull
                                # requests actually target, falling back to
                                # `origin/HEAD` — which is a pointer nobody
                                # updates, so a repo that moved to `dev` still
                                # answers `main`.
    forge: github               # the code host (forges/): github or
                                # azure_devops. Inferred by init from origin.
    azure_devops:               # only for forge: azure_devops. Decoded, not
      org: ""                   # percent-encoded: `%20` handed to
      project: ""               # `az repos --project` names a project that
      repo: ""                  # does not exist.
    profile: python-uv          # toolchain profile: python-uv, or node-npm. The repo-wide
                                # default; a project below may set its own.
    infra: none                 # infrastructure profile: docker or none
                                # (infra/). What the repo runs on, apart from
                                # its language; `docker` records the container
                                # listing beside an e2e-test result, `none`
                                # (the default) records nothing. `abk init`
                                # writes `docker` when the root has a compose
                                # file or Dockerfile. An unknown name fails
                                # when abk.yaml loads.
    projects: []                # where each project inside the repo lives, so
                                # unit-test runs its checks *inside* it:
                                #   - path: services/api
                                #     languages: [python]
                                #     profile: python-uv
                                # A file belongs to the deepest project holding
                                # it. Left empty, checks run at the repo root —
                                # which fails outright when the repo root is not
                                # a project (`uv run pre-commit` cannot resolve
                                # pre-commit there). Written by `abk init`.
                                # A project whose directory does not exist in
                                # the checkout being checked is *pending*:
                                # unit-test and e2e-test run nothing in it and name it in
                                # their output, `abk doctor` lists it as
                                # information, and none of it fails. It stops
                                # being pending when the directory exists, so
                                # the unit that creates it is checked in full.
    languages: []               # e.g. [python]; informs init's research
    description: ""             # one paragraph, for prompts and the
                                # planning context
    consumes: []                # repos this one depends on: deploy order
                                # (consumed first), which dev stack a unit's
                                # own comes up on top of, planning order
    relationships: ""           # prose for the planner about how this repo
                                # relates to the others
    tests:
      root_extras: []           # extra packages the repo-root tests/ (outside
                                # every workspace member) need
      e2e_marker: local_stack   # the pytest marker on tests needing the real
                                # stack (e2e-test, and post-merge verify); for a
                                # node project a file-name segment instead:
                                # `<name>.local_stack.test.ts`
      e2e_sandbox:              # what an [e2e-test] step's sandbox allows beyond
        read: []                # a unit-test step's; no other step gets any of
        write: []               # it. Relative paths are taken from the worktree.
        hosts: []               # `abk.local.yaml` adds to these lists per machine.
        ports: []               # local TCP ports opened beside the proxy's, such
                                # as a database's: `[5432]`
      fix_command: null         # argv that applies this repo's formatters and
                                # fixers; the unit's file names are appended and
                                # it runs in each project's directory; null
                                # follows the profile's fix_command, [] turns the
                                # fixer pass off
      e2e_unit_scope: null      # own | full for this repo; null follows limits
      e2e_schedule: null        # daily | weekly | monthly | 'off' for this repo; null follows limits
      dev_stack_marker: dev_stack
                                # the marker on e2e-test tests only the dev stack
                                # can run; left out of post-merge verify
      replay: null              # record and replay of the calls e2e-test tests make outside
                                # the stack; absent = none. Set, it holds:
                                #   upstreams: [{name, url, kind, env, keyed_headers}]
                                #     kind: deterministic | llm; env: the variables that
                                #     point the code under test at the proxy; keyed_headers:
                                #     the request headers that are part of a key
                                #     (default content-type, accept)
                                #   directory: tests/cassettes
                                #   max_age_days: 30          # deterministic upstreams
                                #   llm_max_age_days: 14      # llm upstreams
                                #   max_body_bytes: 2097152   # a larger response is not recorded
                                #   max_directory_mb: 100     # past it nothing more is promoted
                                #   review_after_runs: 5      # a cassette waiting longer is warned about by
                                #                             `abk doctor` and by the next run
    checks:
      affected:
        mode: off               # off | profile | command: which tests the check
                                # after a failed check and a fix runs first.
                                # `profile` asks the toolchain profile's
                                # `affected_test_commands`; `command` runs the
                                # template below. Lint always runs in full, a
                                # selected failure goes back to the fixer, and a
                                # selected pass is confirmed by one full run, which
                                # alone makes a unit green. The first check, a
                                # rework's check and every gate run in full, and so
                                # does a selection that cannot be made or run
        command: null           # required for `command`: a template whose words
                                # `{changed_files}` and `{failed_ids}` each become
                                # one argument per file or test identifier, run in
                                # the project directory under the unit-test time limit;
                                # the profile's "no tests collected" exit counts as
                                # a pass, and the full run still confirms it
    dev_stack: null             # {script: scripts/dev-stack.sh}: a script with
                                # `up`, `test` and `down`. E2e-test runs the
                                # unit's branch on it instead of the live
                                # stack. null = no dev stack.
    agent_commands: null        # the commands the build prompts tell an agent it may
                                # run: a list of {purpose: test|lint|format|check,
                                # command: "uv run pytest -q {path}", scope:
                                # whole|file|node-id}, a string split into
                                # arguments, `{path}` there exactly when the scope
                                # is not `whole`. null follows the toolchain
                                # profiles; a list, `[]` included, replaces them.
                                # Each must match the build allow-list (the tool
                                # list the build starts with) or the load fails
    changelog: CHANGELOG.md     # where the repo keeps its changelog. Set, the
                                # build, rework, resolver and review prompts
                                # carry its convention and unit-test runs
                                # `abk changelog check`; null = off. The
                                # convention is the `## Changelog` section of
                                # the repo's AGENTS.md, else its CLAUDE.md,
                                # else the framework's packaged text.
                                # `abk doctor` warns when the file is absent.
    deploy:
      needs_ssh_agent: false    # image builds that fetch a dependency over
                                # SSH need an agent holding the key
      ssh_key: null             # the key that agent loads
      agent_for:                # commands (by first argv word) run inside it
        - scripts/deploy.sh
        - scripts/deploy-blue-green.sh
      live_written: []          # paths the running system writes into the
                                # checkout; ignored when checking main is
                                # clean before a deploy
      rules: []                 # first match wins; test and doc paths never
                                # match, and a change in a library member
                                # counts for every member depending on it
      # - prefix: svc-a/        # a directory (trailing slash) or a file
      #   run:                  # argv lists, run from the checkout in order;
      #     - [scripts/deploy.sh, svc-a]
      #                         # [] = nothing to deploy
      credentials: null         # credentials the live tests read:
      #   names_from:
      #     file: scripts/dev-stack.sh
      #     shell_array: TEST_CREDENTIALS   # `NAME=(A B C)` in that script
      #   values_from: .env     # an env file, relative to the checkout
  app:
    path: /srv/src/app
    slug: example/app
    consumes: [platform]
    dev_stack: {script: scripts/dev-stack.sh}
    deploy:
      rules:
        - prefix: svc-a/
          run: [[scripts/deploy.sh, svc-a]]
        - prefix: docs/
          run: []

verify:                         # post-merge verification (docs/architecture.md)
  # stack_versions_command: [docker, ps, --format, "{{.Names}}\t{{.Image}}"]
                                # recorded beside an e2e-test result so a
                                # reviewer can see what the stack was; one
                                # `name<TAB>image` per line. Resolved in
                                # order: a list here (an override for every
                                # repo) > the repo's `infra:` profile's
                                # command (`docker`: the container listing
                                # `docker ps --format "{{.Names}}\t{{.Image}}"`;
                                # `none`: nothing) > nothing. Leaving the key
                                # out is not the same as `null`, which
                                # records nothing whatever the repo's
                                # profile. A command that cannot start is
                                # logged and records nothing. An
                                # installation that relied on the old
                                # built-in default now gets `none` and stops
                                # recording until each repo names
                                # `infra: docker`.
  env: {}                       # environment handed to the live-stack tests —
                                # a unit's e2e-test and the check after a merge
                                # alike — each value resolved by a provider
                                # when the run starts (below)

notifications:                  # tell a person when a unit waits on them (off by default)
  provider: off                 # off | command | windows
  delay_minutes: 10             # a card waits this long before it is shown, so one that
                                # clears in the meantime is never raised
  remind_after_minutes: 30      # a card still standing is shown again this often; 0 never
  command:                      # the `command` provider: argv templates split like a shell
    show: ""                    # would, never run through one. Placeholders {id} {title}
    clear: ""                   # {body} {link}; `clear` takes only {id}. `show` is required
                                # for the provider `command`.
                                # The `windows` provider needs none: it raises toasts
                                # through BurntToast pinned to 0.8.5 (`abk init` installs
                                # it, `abk doctor` checks that version is listed).
```

### `project_limits.max_concurrent_restacks`

A unit whose only reason to run is that its base moved runs its whole moved-base run in the
restack lane: the move, the resolver, the port of a conflict and the checks and review of the
moved branch. The lane's cap bounds the moved-base run. The run counts toward slot occupancy but
is never held back by the limit `max_concurrent_stacks`: no build starts at or above that cap,
and the occupancy may read over it. A run stops before any work that is not about the move (a rework of other feedback, a fix of checks, the end-to-end tests, tests or implementation),
and what it cannot go on with is handed back,
`planned` with the cause `restack_handed_back`. The attempts at one base tip are bounded by
`global_limits.max_review_rounds`, after which the unit is held for a person. Every limit in
`project_limits` is counted for each project, not across all repos.

### `planning.self_pull` and `planning.publish`

- `planning.self_pull` (default `true`): in a pipeline worktree, a tick or a track
  first syncs it to the tip of the default branch by fast-forward. It stops,
  with one `planning sync stopped: <reason>` line, on an unfinished merge or
  rebase, a stray branch or a divergence, and never stashes or resets (a file is
  removed only when the incoming commits hold it byte for byte). In a separate
  planning repo it governs the tracks' checkout and `pull --ff-only` (the tick does not
  pull). `false` skips each of these.
- `planning.publish` (default `direct`; `direct` | `branch`): where the tracks'
  planning commits go. `direct` pushes them to the default branch. `branch` pushes
  `planning/<run>-<project>-<phase>` and opens a pull request, for a default
  branch that is protected. Archive is not affected: the tick commits nothing.

When a repo in `abk.yaml` is the planning root's own repository (`path: .`), the
root plays one of three roles: **separate** (no repo shares it), **working copy**
(where a person works; the pipeline never changes its branch, files or index) and
the **pipeline worktree**, a detached worktree `abk install-timers` makes outside
the repository and records in the marker `abk-pipeline-worktree` in the
repository's common git directory. In a working copy, `abk status` and `abk doctor`
name the live pipeline worktree and print `abk --config <worktree>/abk.yaml <command>`;
`abk tick`, `abk track`, `abk verify` and `abk archive` refuse (exit 2) there unless a
config is named with `--config` or `ABK_CONFIG`. `planning.publish` applies only in a
pipeline worktree; `planning.self_pull` also governs a separate planning repo.

### Env providers

`verify.env` maps a variable name to a provider, discriminated by `from`.
Values are resolved when verification runs, never stored, and `abk doctor`
reports only whether each resolves.

```yaml
verify:
  env:
    CONSUMER_KEY:
      from: literal
      value: not-a-secret
    PLATFORM_TOKEN:
      from: env-file            # a KEY=value line in a file (quotes stripped)
      file: /srv/src/platform/.env
      key: PLATFORM_TOKEN
    GATEWAY_KEY:
      from: yaml                # a dotted path into a YAML document
      file: /srv/src/app/config.yaml
      path: gateway.auth.header # e.g. "Bearer abc" ...
      take: last-word           # ... -> "abc" (optional)
      strip_prefix: ""          # removed from the value first (optional)
    SESSION_TOKEN:
      from: command             # stdout of a command, stripped; a non-zero
      argv: [pass, show, app/session]
                                # exit fails the verification
```

### Where an installation's facts live

The tracked `abk.yaml` of a public repo holds neither consumer facts nor user-specific values:
no other repo's path, owner or name, no home directory, no command that belongs to one machine.
Two ignored files in the planning root hold what you would otherwise write there, and `abk init`
adds both to `.gitignore`.

`.env` is for single values and secrets you would write in `abk.yaml` but not commit: an
agent command, a local port, a token. `abk.yaml` keeps the entry and reads the value from the
file through a `from: env-file` provider with generic variable names:

```yaml
verify:
  env:
    AGENT_COMMAND:
      from: env-file
      file: .env
      key: AGENT_COMMAND
    SERVICE_TOKEN:
      from: env-file
      file: .env
      key: SERVICE_TOKEN
```

`abk.local.yaml` is for structured, user-specific configuration, merged over `abk.yaml` when
it loads (mappings merge by key; lists, text and `null` replace). A worked example of
abk.local.yaml, holding one user's checkout of a repo and an extra verification variable:

```yaml
repos:
  platform:
    path: ../platform
verify:
  env:
    EXTRA_TOKEN:
      from: env-file
      file: .env
      key: EXTRA_TOKEN
```

A second Claude account is set the same way, wholly in `abk.local.yaml`: which account builds a
repo (`repos.<name>.account: kit`) depends on who runs the pipeline and which accounts they have,
so it is a machine choice, and the label's directory is given beside it. A person with one account
sets nothing, and a repo with no `account`, or whose label has no `config_dir` on the machine, runs
on the default account.

A pause follows the account: a rate limit or a usage refusal on one account pauses that account
(`paused.<label>.json` in the state directory, `paused.json` for the default account) and no other,
so the other accounts' units keep starting. A network outage pauses every account.

```yaml
runtimes:
  claude_code:
    accounts:
      kit:
        config_dir: /path/to/.claude-kit        # absolute; refused in the committed abk.yaml
        max_units_in_progress: 3                # this account's own slots
        limits: {}                              # same shape as runtimes.claude_code.limits
```

Units in progress are counted per account against that account's `max_units_in_progress`
(the default account's is `project_limits.max_units_in_progress`) once an installation names an
account. From then on `project_limits.max_units_in_progress` bounds the default account's units
across all its projects together, not each project, and that includes a repo whose label has no
directory on this machine, so a person with one account sees the one limit shared by every repo. `abk report --by account` groups the ledger by account.

What counts against `max_units_in_progress` includes a started unit (`running` with a branch) that a
usage pause parked before its agent step: it holds its place and shows as `paused` in the full-queue
line. At admission, before `prepare`, a ready unit is checked against its own account's usage decision;
a refused unit waits with `usage_pause` naming the account. `max_concurrent_stacks` is counted for each
project, not for each account.

They are independent layers, and both may be used. For a fact either could carry, the loader
reads the entry itself (which `verify.env` variable exists, and its provider) from `abk.yaml`
merged with `abk.local.yaml`, and reads that entry's value from the file its `env-file`
provider names, `.env` here. Nothing reads `.env` for the entry itself.

A planning repo that plans only itself needs no other repo entries: its own entry, with path
`.`, is the checkout naming itself.

#### Which file holds a setting

`abk config --migrate` moves the machine settings in this table out of a tracked `abk.yaml`;
`--include-defaults` adds the defaults a team may commit.

Put a value in `abk.local.yaml` when it names something on one machine or measures what one
machine or subscription can do; keep it in `abk.yaml` when every checkout of the planning repo
should agree on it. Keep the entry's other keys in `abk.yaml` and give `abk.local.yaml` only the
key that differs, since mappings merge by key:

| Setting | File | Why |
|---|---|---|
| `repos.<name>.path`, `repos.<name>.deploy.ssh_key`, `planning.worktree_root` | `abk.local.yaml` | a path on this machine; use `~` or a path relative to the planning root |
| a `verify.env` entry that reads a file in the home directory or holds a home path | `abk.local.yaml` | the same value is a different path on another machine |
| `runtimes.<name>.limits`, `runtimes.claude_code.accounts.<label>.config_dir` | `abk.local.yaml` | the pause thresholds belong to this person's subscription windows, and a config directory is a path |
| `project_limits` | `abk.local.yaml` | how many units and stacks this machine can run at once |
| `sandbox.write`, `sandbox.read` (paths) and `sandbox.hosts` | `abk.local.yaml` for a path on this machine, `abk.yaml` for what every checkout shares | what an agent step may write, read and reach; `sandbox.enabled`, `sandbox.backend` and a repo's `sandbox.required` stay in `abk.yaml` |
| the rest of a repo's entry (`slug`, `profile`, `tests`, `deploy.rules`, `consumes`, `relationships`) and `global_limits` | `abk.yaml` | how the work is planned, built and deployed, which every checkout shares |
| a token, a port, an agent command | `.env`, read by a `from: env-file` provider | a secret or a single value, not structure |

Split by key, not by block. For example the tracked file names the repo and the local file says
where it is checked out:

```yaml
# abk.yaml
repos:
  platform:
    slug: owner/platform
    profile: python-uv
```

```yaml
# abk.local.yaml
repos:
  platform:
    path: ../platform
```

A fresh clone has no `abk.local.yaml`: until its owner writes one with the checkout paths,
`abk` has nothing to plan against, and `abk config --show` names the file it merged (and the
top-level keys it set) on its first line, so a missing or misplaced entry is easy to see.
Lists, text and `null` replace the tracked value, so a local `deploy.rules` or `consumes`
discards the tracked list rather than extending it.

Words that only this installation knows go in `scrub.local`, one per line (`!word` removes a
derived term); `abk scrub-check` reads it. `abk doctor`'s `public content` check warns when
`abk.local.yaml` or `scrub.local` is tracked or not ignored, and when a committed `abk.yaml`
holds a repo path outside the checkout, a home path or another account's repo.

### `sandbox`

The kernel confines what an agent step can write and reach. Keys:

- `sandbox.enabled` (default `false`): turn the sandbox on.
- `sandbox.backend` (default `auto`): `auto` picks the first backend whose probe passes on this
  machine; or name one (`landlock` today; `seatbelt` arrives with the macOS backend and is refused at
  load until then).
- `repos.<name>.sandbox.required` (default `files`): the least coverage a step may run with
  (`process`, `files` or `none`; `none` lets it run unconfined).
- `sandbox.write`, `sandbox.read` and `sandbox.hosts`, on a repo or a project: extra paths and
  hosts, in `abk.yaml` and `abk.local.yaml` (see the table above for which holds what). An ACP
  agent's own model host is not added for it: list it under `sandbox.hosts`.

The config guard reads `abk.yaml` and `abk.local.yaml` before an agent step and again after it. A
step that was not confined fails with `ConfigChanged` when either differs. During a confined run a
person may edit them: the step's coverage is `process` or `files`, so a difference is logged as a
warning with its diff, shown by `abk status`, and the unit continues. A track run is not confined
yet, so it still fails.

The guards by class: the config guard and the text fence on these two files are location guards, so
they stand down for a confined step and apply to one that is not; the guards about meaning (no
merge, no push, no commit where forbidden) apply either way. See
[sandbox-design.md](sandbox-design.md) for the table.

`abk doctor` and `abk init` run the backend's probe and print the cause and the fix when it fails;
`abk policy check` and `abk status` show each runtime's `sandbox_coverage` beside its
`policy_coverage`. The design is in [sandbox-design.md](sandbox-design.md).

### `review`

The review policy, a build-out section for risk-tiered review. A person edits it; a build agent
and a track are refused a write to `abk.yaml` or `abk.local.yaml` by the routes the command policy
names (a file write, a shell redirect, an editor command, and its copy and in-place edit programs).
A command cannot be parsed for every route, so the pipeline also reads both files before every build
and track run and again after it: a run after which either differs fails, naming the file and showing
the difference. The file is not restored, and a person's edit during a run fails it the same way (the
message says so, so the unit can be requeued once the edit is done).

```yaml
review:
  protected_paths: []      # globs added to the framework's defaults
  protected_defaults: true # migrations, CI and deploy config, containers, secrets, CODEOWNERS
  classes: {}              # name -> path globs; no slash in a name; the first listed class wins
  auto_land: {min_samples: 20, min_clean_rate: 0.95, allow_deferred_e2e: false, classes: []}
  audit: {sample_rate: 0.1}                        # share of landed units a person is asked to look at, 0 to 1
  demotion: {window: 30, min_agreement: 0.9}       # recent outcomes counted (>= 1) and the agreement they need, 0 to 1
  ceilings: {auto: 5000, light: 2000, full: 750}   # estimated changed lines a unit may carry, by expected tier
  ceiling_buffer: 0.2      # a unit is held for its size only past its ceiling times one plus this
  split_rounds: 2          # plans a unit's lineage may spend splitting it; 0 sends every such unit to a person
  brief: true              # a pull request body opens with "Start here"; false keeps the older layout
repos:
  app:
    review:
      protected_paths: []           # added to the workspace's list for this repo, never narrowing it
      ceilings: {light: 1500}       # overrides this one tier for this repo; the others stay the workspace's
```

`review.ceilings` sizes a unit by its expected review tier: `auto` 5000, `light` 2000 and `full` 750
by default, and `full` must stay above `global_limits.min_unit_lines`, `light` must not be below
`full` and `auto` must not be below `light`. A repo's `review.ceilings` may override any one tier
for that repo; the merged ceilings must keep the same order. Review by tier is always on. A file
that still sets the removed key `enabled` under `review` loads with the key ignored, and
`abk config` and `abk doctor` say it is no longer used.
A file that still sets the old single ceiling fails to load, naming `review.ceilings.full`;
`abk config --migrate` moves the value. A unit that lands over its ceiling is logged and listed by
`abk status`, never blocked. A plan recorded under other sizing is stale: a plan is
stale when anything in the `review` section changes (its ceilings, protected paths, classes or
auto_land), a repo's `review` block changes, or `global_limits.min_unit_lines`
changes (see `abk replan` in `docs/cli.md`).

Once `auto_land.classes` is not empty, `abk doctor` warns for each repo with no branch protection
(the command policy hook does nothing against the pipeline's own merge).

`review.ceiling_buffer` (a fraction from 0 to 1, default 0.2) and `review.split_rounds` (an integer
from 0 to 2, default 2) govern a built unit that turns out larger than planned. A unit whose changed
lines pass the ceiling of the tier it earned times one plus the buffer is held by size and replaced
by smaller units; `split_rounds` counts the splits along a unit's lineage, and 0 sends every such
unit to a person. The configuration fails to load when the buffered `auto` ceiling of the workspace
or of any repo would reach the reviewer's reading limit of 10,000 lines, since a unit that large
cannot be read by the reviewer at all. `abk doctor` prints the buffered ceilings and warns above 80%
of that limit, and when `split_rounds` is 0 with review enabled. The planner never reads the buffer.

`auto_land.allow_deferred_e2e` (default false; accepted only under
`review.auto_land`) decides what a deferred e2e-test result is worth. The verdict reads a unit's e2e state as `passed`, `deferred`, `failed` or
`not-required`: `failed` is `full`, `deferred` holds the unit at `light` unless the key is true,
and `passed` and `not-required` add no floor. A unit of the e2e-test kind with no recorded state
is a missing gate and is `full`. No setting lowers a tier another floor set.

A unit belongs to the first class whose globs match every path it changed, else `<repo>/<kind>`
(`unit-test` or `e2e-test`; an `integration-test` unit is a `unit-test` one). `abk doctor` warns for a
glob that matches no file in any repo and for policy set while `enabled` is false, and fails for a
glob that does not parse.

### `redact`

`redact: [NAME, ...]` lists environment variables whose values are secrets the framework
has no field for. Each value is read from the process environment and the planning root's
`.env`, and is replaced by `[redacted:NAME]` wherever the pipeline stores or sends text,
as the `verify.env` values and the credential settings are. A value under 8 characters is
not replaced, and `abk doctor` warns, by name, for such a variable and for a name that is
not set. See "Secrets never leave as text" in `docs/architecture.md`.

### `tests.e2e_splits`

`tests.e2e_splits` divides a repo's e2e-test tests into named splits that can be run, held
and scheduled apart. The key is `e2e_splits`; its earlier, numbered spelling still loads,
with a deprecation notice, and a file setting both is refused.
It sits under `tests` at the top of `abk.yaml`, or under a repo's own `tests`, where it
replaces the top-level map for that repo.

```yaml
tests:
  e2e_splits:
    slow:
      marker: slow_stack      # the selector: a marker the test runner registers
      hold: false             # optional; true holds the split
repos:
  app:
    tests:
      e2e_splits: {}        # this repo declares none, whatever the top level says
```

- A split name is lowercase letters, digits and underscores; `base`, the older name of
  `rest`, is reserved and refused. Each split has a `marker`
  (non-empty, not shared with another split), an optional `hold` and an optional `gate`
  (the provider of its model, or a command, with its limits; `abk config --show` prints it).
  An unknown key, a missing marker or a repeated one is refused when the file loads.
- `rest` is always declared: it is the tests in no split. It may carry `hold` but no
  `marker`, and needs no entry. With no splits declared, a repo's splits are `rest` alone.
- A test is in at most one split. `abk e2e-test check` finds a test in two.
- A test that needs the shared telemetry stack carries the marker `telemetry_otel` (it needs the
  stack's dev instance and the `ABK_ACCEPTANCE_*` variables). A machine without the stack
  declares `telemetry: {marker: telemetry_otel}` and holds that split, rather than skipping
  the test: a live test whose dependency is missing still fails.
- The splits a repo declares are what a `Split:` line in a change's e2e-test group may name (see
  `e2e_splits` of the repo, or the top level when the repo declares none of its own); a group with
  no line is in `rest`. A group is in one split, so a test that must run in two is written as two
  groups.
- `hold: true` leaves a split out of every e2e-test run and parks the units that wait on it.
  `abk e2e-test hold` and `abk e2e-test release` write `hold` in `abk.yaml` and an entry in the
  state file `e2e-held.json` together. The configuration wins: `hold: false` always
  releases a split and `hold: true` always holds it, whatever the file says; the file
  decides only for a split with no `hold` set.
- The three runtime lists this setting replaces are gone, with no alias, and are refused at
  load with a pointer to the split setting that replaces each (`tests.e2e_splits`).

### `tests.e2e_dimensions` and `tests.e2e_available`

A split divides tests by time and cost; a dimension says what a test needs. `tests.e2e_dimensions`
(top level, or under a repo's own `tests`, which replaces it for that repo) declares groups of
values, each value with a pytest marker, and `tests.e2e_available` lists the values a machine has.

```yaml
tests:
  e2e_dimensions:
    runtime:
      claude_code: {marker: runtime_claude_code}
      acp: {marker: runtime_acp}
    telemetry:
      otel: {marker: telemetry_otel}
      local: {marker: telemetry_local}
  e2e_available:
    telemetry: [local]      # this machine has no telemetry stack
```

- A test carries at most one value of each dimension (its own marks, its class's, its module's
  and a parameter's); a test with none in a dimension is neutral to it. `abk e2e-test check`
  finds a test with two values of one dimension.
- A marker belongs to one value or split only, and `e2e_available` may name only declared
  dimensions and values; both are refused when the file loads.
- `e2e_available` sits in the committed file or in the machine-local overlay `abk.local.yaml`, which
  is merged key by key. A dimension with no entry has every value.
- A run leaves out every test carrying the marker of an unavailable value, whatever the holds
  and for a single split too. A scheduled split with nothing runnable is skipped with
  "nothing runnable: needs <dimension>=<value>", fails nothing and parks no unit. A test whose
  value is available but whose dependency is down still fails.
- `abk e2e-test status` and `abk doctor` show each dimension, its values and which are available.

Writing convention: a live test that works across a dimension's values is one parametrized test
with a name that holds no value, the value appearing in the parameter id. No two live tests
differ in name only by a value; the drift test says "merge into one parametrized test". A
value-neutral name holds a value token only when it is the only test carrying that value.

## Environment variables and `.env`

`settings.py` reads these with pydantic-settings: from the process
environment, and from the planning root's `.env` once the installation is
loaded (`abk init` writes `.env.example` to copy).

| Variable | Meaning | Default |
|---|---|---|
| `ABK_CONFIG` | the `abk.yaml` to use, when it is not the nearest one above the working directory | unset |
| `ABK_GATEWAY_SETTLE_SECONDS` | how long after a call ends its gateway spend rows are waited for, since a gateway writes its logs in batches; the bound on the whole wait | `30` |
| `ABK_GATEWAY_QUIET_SECONDS` | how long a call's gateway spend rows must have stopped growing before they are taken as complete; set it to at least the gateway's flush interval. Rows still arriving at the settle bound are used and the log says the totals may be incomplete | `10` |
| `GH_TOKEN` (or `ABK_GH_TOKEN`) | one GitHub token for every GitHub call, instead of the per-owner lookup `gh auth token --user <owner>`. Read from `.env`, since pydantic-settings does not export to the environment. | unset: per-owner lookup |
| `ABK_GITHUB_API_URL` | the address GitHub calls go to, for GitHub Enterprise or a stand-in host. On an Enterprise host set `GH_TOKEN`: the `gh auth token` lookup asks github.com | `https://api.github.com` |
| `ABK_REPLAY_MODE` | what e2e-test tests do with the calls they make outside the stack: `off` (no listener, nothing changed), `record` (all live, a passing test's calls are written), `replay` (an exact, fresh match answers from its cassette; anything else goes live and is recorded) or `live` (cassettes ignored, recordings written as in `record`). Any other value is refused | `off` |
| `ABK_FORGE_TIMEOUT_SECONDS` | the timeout on every call to a code host | `30` |
| `ABK_FORGE_RETRIES` | how many times a failed code-host call is retried after the first attempt | `3` |
| `ABK_FORGE_DEADLINE_SECONDS` | the most time, from a code-host call's first attempt, that retries and their waits may take | `120` |
| `ABK_WORKTREE_ROOT` | overrides `planning.worktree_root` on this machine | unset |
| `ABK_OPENSPEC_VERSION` | the `@fission-ai/openspec` version run through `npx`; a pin, so an upgrade is a deliberate change | `1.13.1` |
| `ABK_USAGE_GUARD` | `on` or `off`; `off` makes the process take no usage reading and never pause for usage. For scratch installations of live tests; it is not an `abk.yaml` key and is never read from the file. Any other value is refused | `on` |
| `ABK_RUNTIME` | overrides `runtime` on this machine, so a runtime can be tried on one invocation without moving every repo in the workspace | unset: the file's |
| `ABK_IMPLEMENT_MODEL`, `ABK_REWORK_MODEL`, `ABK_REVIEW_MODEL`, `ABK_REWORK_REVIEW_MODEL` | per-machine overrides of the active runtime's `runtimes.<name>.models.*` | unset: the file's |
| `ABK_GATEWAY_URL`, `ABK_GATEWAY_MASTER_KEY` | the model gateway and the master key that may mint keys on it. Set both and each agent call gets a key of its own, its usage is read from the gateway's records and the key is revoked afterwards; set neither for no gateway; one alone is said once and mints nothing | unset |
| `ABK_OTEL_ENABLED` | the one switch for telemetry (traces and metrics, see `telemetry.py`); nothing OpenTelemetry is imported while it is false. Needs the `telemetry` extra (`pip install agent-build-kit[telemetry]`); without it one line says so and the run carries on | `false` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | the OTLP/HTTP collector base URL; `/v1/traces` and `/v1/metrics` are appended | unset |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | per-signal full URLs, overriding the shared endpoint (traces and metrics usually have different intake ports) | unset |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | passed to the resource (`k=v,k2=v2`) | `agent-build-kit`, unset |
| `ABK_GRAFANA_URL`, `ABK_GRAFANA_TOKEN` | the Grafana `abk telemetry push-dashboard` pushes the pipeline's dashboard (package data) to, and an optional service-account token; with no token the push is anonymous (no authorization header), and a 401 or 403 then names `ABK_GRAFANA_TOKEN`; a missing URL is named and exits non-zero; `abk doctor` says which path is used | unset |
| `ABK_GRAFANA_FOLDER` | the folder the dashboard goes into, created when missing; pushing again overwrites the one dashboard | `agent-build-kit` |
| `ABK_PROMETHEUS_URL`, `ABK_TEMPO_URL` | the stores `abk serve`'s metrics page queries (Prometheus for the charts, Tempo's search for recent traces); empty or not answering means the page draws from local files and says so | unset |

A bad collector cannot fail or slow a run: exports are batched, a failure is
at most a warning, and `shutdown()` is bounded. `abk doctor` warns when
telemetry is enabled with no endpoint or one that does not answer.

The flat top-level `models:` block is deprecated. It still loads, for the active
runtime only, with a notice naming `runtimes.<active>.models` (which
`abk config --migrate` moves it to); a role set in both places takes the runtime's
value. Set the roles under `runtimes.<name>.models`.

The model overrides name the *active* runtime's models: a role's model is
resolved against whichever runtime is selected, so an override naming a model
one runtime knows and another does not applies only while that runtime is in
force. See [agent-runtimes.md](agent-runtimes.md).

`CLAUDE_CODE_OAUTH_TOKEN` is read outside the settings layer because it belongs
to Claude Code: the usage guard uses it ahead of the token stored in the account's
directory.

### The Claude Code account

The account is the Claude Code config directory, set as `CLAUDE_CONFIG_DIR` or
`ABK_CLAUDE_HOME` in the installation's `.env` or the process environment. The two
names are aliases of one value: `CLAUDE_CONFIG_DIR` is read first within a place, the
process environment beats the `.env`, an empty value is unset, and a relative path is
refused. Neither set means the default `~/.claude`. It is not an abk.yaml key: it names
a directory that differs per user and per machine, and abk.yaml is checked in.

What each command does with it: every `claude` the pipeline starts runs in the
account's directory; the usage guard reads the credentials and `.claude.json` inside it;
the sessions page lists and resumes its sessions; `abk install-skills --user` writes to
its `skills` directory; `abk doctor` prints the directory, which name and place supplied
it, whether it exists and whether it is logged in.

Two installations on two accounts keep their own usage cache, record, allowances,
ledger and timers. They share the machine, the `claude` binary and the editor
extension's own setting. The how-to is [claude-code-second-account.md](claude-code-second-account.md).

## Reaching the config from code

`Installation` (`installation.py`) loads the file and derives every path from
it: `state_dir`, `specs_dir`, `changes_dir`, `graph_page`, `usage_page`, `worktree_root`,
`checkouts`, `deploy_order`, `dev_stack_base`, `verify_env`. The CLI passes
that object to every command. Leaf modules that need one scalar — a limit, a
prefix, a model — call `config.active()`, set once by `Installation.activate()`
and defaulting to an empty workspace so the library is usable without a file
on disk. `config.runtime_name()` is the runtime in force (`ABK_RUNTIME`, then
`runtime`), and `runtimes.active()` its adapter; `config.runtime_entry()` is
its `runtimes.<name>` entry, or an empty one. `config.models()` resolves each
role from the `ABK_*_MODEL` overrides, then that runtime's
`runtimes.<name>.models`, then a role the flat `models` block names, then the
adapter's own `default_models`.
