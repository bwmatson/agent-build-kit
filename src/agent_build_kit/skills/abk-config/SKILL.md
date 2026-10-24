---
name: abk-config
description: TRIGGER — read before editing abk.yaml in a planning repo, when `abk doctor` reports a problem, or when asked where an installation fact (a repo path, a GitHub owner, a deploy command, a credential name) should live. SKIP for questions about running the pipeline (abk-pipeline) or writing a change's tasks (abk-authoring).
version: 1.1.0
generatedBy: agent-build-kit
---

# abk.yaml and `abk doctor`

Everything that describes one installation — which repos, where they are
checked out, who owns them on GitHub, how each one deploys, what the planner
should know about how they relate — lives in `abk.yaml` in the planning
repo and nowhere else. The framework knows nothing about any particular
installation; a fact that belongs to one goes here, not in a prompt, a skill
or a script. Machine-local values (tokens, a worktree root override, model
overrides, `ABK_RUNTIME`, the gateway pair `ABK_GATEWAY_URL` and
`ABK_GATEWAY_MASTER_KEY` (set both or neither: each agent call then gets a
key of its own and its usage is read from the gateway's records), the
code-host call bounds `ABK_FORGE_TIMEOUT_SECONDS`, `ABK_FORGE_RETRIES` and
`ABK_FORGE_DEADLINE_SECONDS`, the GitHub address `ABK_GITHUB_API_URL` (an
Enterprise host needs `GH_TOKEN` too), `ABK_REPLAY_MODE` (`off`, `record`, `replay` or `live`: what e2e-test tests do with calls
outside the stack), the telemetry switch `ABK_OTEL_ENABLED` and its
`OTEL_*` endpoints, and `ABK_GRAFANA_URL`/`ABK_GRAFANA_TOKEN`/`ABK_GRAFANA_FOLDER`
for `abk telemetry push-dashboard`, whose token is optional: without it the push is
anonymous) go in the planning repo's `.env`, which is not
committed.

The schema is strict: an unknown key fails at load. `abk config --show`
prints the effective config with every default filled in; `abk config
--path` prints which file is in force (`--config`, then `ABK_CONFIG`, then
the nearest `abk.yaml` above the working directory).

The `e2e_*` settings below apply to the `e2e-test` kind alone. Of the three test kinds
(`unit-test`, `integration-test`, `e2e-test`), `integration-test` is a label that behaves as
`unit-test`: it takes no e2e lock and no `e2e_*` setting, and is not the pytest `integration`
marker.

## Schema

Defaults are shown; a key at its default can be left out.

```yaml
version: 1

planning:
  state_dir: runs             # relative to the planning root unless absolute
  specs_dir: openspec
  graph_page: docs/unit_graph.md
  usage_page: docs/unit_cost.md   # cost summary from the usage ledger (`abk report`)
  worktree_root: null         # where unit worktrees go; never inside the
                              # planning repo; null = a per-user data dir
                              # named after the planning directory
  self_pull: true             # tracks pull the planning repo before running
  publish: direct             # direct | branch: push track commits to the default
                              # branch, or to a planning/... branch with a pull request
                              # (only for a repo that is also the planning repo)

openspec:
  command: null               # argv for the OpenSpec CLI; null = npx with
                              # the framework's pinned version

git:
  push_host: ""               # ssh host alias carrying the key to push agent
                              # branches as; "" = origin
  branch_prefix: spec/        # marks a branch and its PR as agent-owned

runtime: claude_code          # the agent runtime every step runs on;
                              # ABK_RUNTIME overrides it on one machine. An
                              # unknown one fails at load.
runtimes:                     # only for a runtime needing a fact abk cannot
                              # default; only the selected one is checked
  claude_code:                # the subscription's two usage windows, each a section
    models:                   # bare aliases, not pinned ids: this runtime's own names for
      implement: sonnet       # the roles; ABK_*_MODEL overrides win over these. A role
      rework: sonnet          # named nowhere takes the runtime's own default.
      review: opus
      rework_review: opus     # both reviews are made by a different model from
                              # the author; if the author is opus, set this to another
    limits:                   # with the same settings
      session:                # the 5-hour window
        usage_pause_pct: 70            # % at which no unit starts
        usage_pause_ceiling_pct:       # what that rises to at the reset; unset =
                                       # usage_pause_pct, which means no ramp
        usage_relief_fraction: 0.25    # trailing part of the window a ramp spans
        usage_resume_buffer_pct: 5     # room above usage a resume waits for
        usage_unit_allowance_pct: auto # points one unit may spend, for an estimate: `auto`
                                       # calibrates it from history (fallback 10, ceiling 20);
                                       # a number is the fallback and the cap
        usage_allowance_floor_pct: 1   # least a calibrated allowance may be
        usage_estimate_basis: cost     # cost (recorded cost x learned points/$) or units
        usage_estimate_intercept: true # points-per-hour term in the cost fit; on for the session
      weekly:                 # the 7-day window: the same settings
        usage_pause_pct: 70
        usage_pause_ceiling_pct:
        usage_relief_fraction: 0.25
        usage_resume_buffer_pct: 5
        usage_unit_allowance_pct: auto # fallback 2, ceiling 4
        usage_allowance_floor_pct: 1
        usage_estimate_basis: cost
        usage_estimate_intercept: false # off for the weekly
      calibrate_usage_allowances: true # false: use the configured allowances only
      usage_allowance_quantile: 0.9    # of points gained per unit; window 30 pairs, minimum 8
      usage_allowance_window: 30
      usage_allowance_min_pairs: 8
      usage_cost_min_pairs: 8          # pairs with cost needed to fit the cost basis
      usage_cost_quantile: 0.9         # quantile of the cost fit's scale
      usage_forecast: true             # forecast a start from its review tier's history
      usage_forecast_min_runs: 10      # units a tier needs before its history is used
      usage_forecast_quantile: 0.9     # quantile the chance of each step is bounded at
      usage_stale_retry_minutes: 5     # refusal length when the reading is too old
      usage_cache_minutes: 15          # how long a good usage reading is reused (the shortest)
      usage_claude_cache_minutes: 15   # freshness of Claude Code's own usage block that decides
                                       # with no call; unset follows usage_cache_minutes, 0 is off
      usage_cache_max_minutes: 30      # the most refusals can stretch that to
      usage_fallback_minutes: 30       # age of the last good reading that covers a failed call
      usage_climb_floor: 0.2  # slowest climb, in points a minute, a window is assumed to make
      usage_climb_margin_pct: 2  # points added to what a reading could have gained since
      usage_headroom_margin_pct: 5  # room an estimate must leave under a threshold
      usage_estimate_max_starts: 3  # units that may start on an estimate per reading (0: none)
  # <name>:
  #   command: [some-agent, acp]          # argv that starts its agent
  #   policy_fix: [scripts/constrain.sh]  # offered by init, printed first by doctor
  #   policy_extra: ["git * push --mirror*"]  # own command globs (non-blank, the dialect `abk policy
  #                                       # show` prints), added after the kit's by `abk policy patterns --extra`
  #   policy: unchecked                   # the only value: carried on without checking; doctor
  #                                       # warns and sends no prompt until `abk init --policy-only`
  #                                       # passes and the line is removed
  #                                       # confirming the agent refuses what abk forbids
  #   models: {review: "..."}             # this runtime's names for roles

# The flat top-level models: block is deprecated: it still loads for the active runtime with
# a notice naming runtimes.<name>.models (the active runtime's), and `abk config --migrate` moves it there.

session_reuse:                # per agent role: continue the role's latest session
  build: true                 # tests/implement/fix/rework/restack/adapt share one session
  review: false               # always false: a review starts fresh; a role left out is off

retention:
  decision_log_mb: 50         # size of the decision log and of the admission records; the oldest
                              # lines are dropped past it
  unit_log_days: 30           # age at which a summarised unit's run log is removed

context:
  compaction_drop_share: 0.3  # fall in the fill larger than this share of the window = a compaction
  warn_share: 0.8             # a step ending above this share of the window logs a warning
# runtimes.claude_code.context_windows: {model: tokens}, when the result does not name the window

# Scheduling is set once for every project; there is no per-repo override.
project_limits:
  max_concurrent_stacks: 4    # units implemented at once, in each project
  max_concurrent_restacks: 2  # moved-base runs (a branch moved onto a changed base, and the run after it) at once, in each project; never held back by max_concurrent_stacks
  max_units_in_progress: 5    # (counted per account instead, against `runtimes.claude_code.accounts.<label>.max_units_in_progress`, once an account is named) started, unfinished units (>= 1) in each project, not counting blocked or failed-waiting ones; at it no never-started unit starts
  emergency_extra: 1          # the emergency lane cap, in each project: priority-0 units that may start past the limits above (default 1; 0 is off)

# `limits:` is the deprecated root name of `global_limits:`. A scheduling setting left in either
# fails the load; `abk config --migrate [--yes] [--dry-run]` moves it by text (diff first, one backup).
global_limits:
  stack_depth_build_cap: 3    # longest chain of in-review PRs from main
  stack_depth_rebase_cap:     # deepest a merge restacks a dependent; unset = the build cap
  max_flakes_per_run: 5       # more flaky tests than this in one run are one recorded storm, no fix change each
  checks_register_seconds: 120  # secs after a push a PR with no checks yet reads `checking`
  wait_end_requeue: auto      # auto (default), resume, rework or off: how a failed unit that waited on another unit is requeued once when its wait ends; off leaves it to a person
  bounce_limit: 3             # a unit put back from running this many times in a row with one cause is named looping (>= 2)
  bounce_span_seconds: 120    # a run shorter than this counts as a bounce (>= 1)
  label_sweep_per_tick: 20    # finished units' PRs a round takes a stale state label off (>= 1)
  manual_check_seconds: 30    # seconds a manual step's check script may run (>= 1)
  min_unit_lines: 400         # estimated lines before a unit stops growing
  max_unit_lines: 750         # DEPRECATED: read as review.ceilings.full;
                              # `abk config --migrate` moves it. A unit landing
                              # over its ceiling is reported, never blocked
  calibrate_estimates: true   # estimate x what the unit's kind (repo, tier, flag) landed at
                              # is held to the ceiling; false = the raw estimate
  calibration_window: 20      # newest merged units of a kind sampled (>= 1)
  calibration_min: 3          # fewer samples: ratio 1 (>= 1, not above the window)
  calibration_shrink: 5       # n samples carry n / (n + shrink) of the gap from 1 (>= 0)
  calibration_sample_clamp: [0.5, 4.0]  # each sample held to this (low in (0, 1], high >= 1)
  calibration_max: 3.0        # the ratio is kept between 1 and this (>= 1)
  calibration_examples: 3     # newest merged units of each listed kind shown to the planner (>= 0)
  calibration_kinds_listed: 5 # kinds shown to the planner, most samples first (>= 1)
  generated_files: []         # patterns left out of a unit's actual size; the environments'
                              # lock files are left out as well; init writes the detected ones
  max_review_rounds: 3        # review rounds before a unit fails
  max_check_rounds: 3         # fix rounds for failing checks, per review round; null = no limit; 0 = none (still checked)
  max_adapt_rounds: 2         # adapt-step accounting asks, first included,
                              # before a unit fails
  max_plan_attempts: 3        # times one tasks.md is sent to the planner
  max_check_reruns: 2         # re-runs of a head commit's cancelled checks
  transcript_result_chars: 20000  # longest tool result a transcript keeps whole
  transcript_runs_kept: 3     # runs of one unit that keep their transcript
  # The earlier, numbered spellings of the next keys still load, with a notice, for one release.
  unit_test_command_seconds: 3600   # longest a unit-test command may run before it is aborted
  unit_test_abort_grace_seconds: 10  # how long an aborted command has to exit before it is killed
  unit_test_repeat_runs: 3          # times the tests a unit added or changed are run again under load (0: off)
  restack_check: affected           # unit-test after a clean move: scoped by the files the move brought in (affected) or the whole suite (full)
  e2e_base_runs: 1                  # run the untouched failed e2e-test tests once on the base (0: off)
  e2e_unit_scope: own               # e2e-test per unit: only the tests it added or changed (own) or the whole marker (full); tests.e2e_unit_scope overrides per repo
  e2e_schedule: weekly              # whole e2e-test suite on the default branch: daily | weekly | monthly | 'off' (quote it); tests.e2e_schedule overrides per repo
  e2e_lock_wait_seconds: 5400       # longest post-merge verification waits for the e2e-test lock before reporting it busy
  e2e_durations_shown: 15           # slowest e2e-test test entries the posted result lists (0 = all)
  network_probe_timeout_seconds: 5  # longest the outage probe waits to connect to one host
  network_control_hosts: [one.one.one.one, dns.google]  # bare host names tried beside the code hosts to tell a network outage from a model service outage
  service_unavailable_attempts: 5   # times in a row a 5xx or 529 from the model service parks a unit before the next fails it

environment:                  # how the pipeline's own environment is kept current;
                              # leave it out and nothing is managed (`abk doctor` warns)
  sync: [uv, sync]            # required, not empty: brings the environment up to date
  check: [uv, run, --no-sync, python, -c, "import agent_build_kit"]
                              # required, not empty: exits 0 when it is healthy
  inputs:                     # path patterns relative to the repo (`**` spans folders;
                              # absolute, or `..` with a wildcard, is refused; a plain `..` path
                              # warns and goes in the next release); a literal path matches itself
    dependencies: [pyproject.toml]
    lock: [uv.lock]           # matched by file name, and left out of a unit's size
    other: []                 # inputs that are all absent make the environment pending:
                              # no sync, no check, until one appears
  artifacts: [.venv]          # what sync and check produce: never an input, a leftover or
                              # a commit; a tracked file under it is ordinary work

builders:
  installable_files: []       # base names `abk install-config` may install, besides
                              # .pre-commit-config.yaml; never a path or a pattern
  stubbed_tdd_commits: true     # builders.stubbed_tdd_commits. true = one `test:` (with stubs) and one `feat:` commit per task
                              # group, stubs and tests checked for lint, format and types first;
                              # needs a profile that supports stubs. Default on; false turns it off

tracks:                       # the scheduled health/improve/recommend tracks
  model: sonnet               # Claude Code's alias, sent to any runtime as
                              # is: set it when selecting another runtime
                              # no dollar budget — every phase is bounded by
                              # the same session/weekly usage windows, and
                              # the same ramped thresholds, as limits above
  propose_max_issues: 3       # issues one propose pass writes up as task groups
  allowed_tools: null         # Claude Code --allowedTools syntax; null = built-in
  disallowed_tools: "..."     # both have no effect under the acp runtime
  prompts_dir: null           # a directory overriding the built-in prompts
  raw_output_dir: .last-runs

repos:                        # ordered; a task group's [repo] tag is a key here
  <name>:
    path: /abs/path/to/repo   # the checkout
    slug: owner/name          # GitHub; the owner picks the gh account
    default_branch: main
    profile: python-uv        # toolchain profile: python-uv or node-npm
    infra: none               # infrastructure profile: docker or none; docker
                              # records the container listing beside an e2e-test
                              # result (init writes it when a compose file or
                              # Dockerfile is in the root)
    projects: []              # [{path, profile, languages}]: a project whose directory is
                              # absent from the checkout is pending: unit-test, e2e-test and
                              # doctor skip it and say so, until a unit creates it
    languages: []             # e.g. [python]
    description: ""           # one paragraph, for prompts and context
    consumes: []              # repos this one depends on: deploy order,
                              # which dev stack it comes up on, planning order
    relationships: ""         # prose for the planner about the other repos
    tests:
      root_extras: []         # extra packages the repo-root tests need
      fix_command: null       # repos.<name>.tests.fix_command: the argv that applies the repo's
                              # formatters and fixers (file names appended) before each commit;
                              # unset follows the profile, [] turns the pass off. Policy, so it
                              # goes in abk.yaml, not abk.local.yaml
      e2e_sandbox:               # what an [e2e-test] step's sandbox allows beyond a unit-test
        read: []                 # step's; no other step gets any of it. Relative paths are
        write: []                # taken from the worktree. `abk.local.yaml` adds to these
        hosts: []                # lists per machine.
        ports: []                # local TCP ports opened beside the proxy's, e.g. `[5432]`
      e2e_marker: local_stack    # for a node project the marker is a file-name segment:
                                 # `<name>.local_stack.test.ts[x]` (`<name>.<marker>.test.<ext>`)
                                 # is e2e-test. Unit-test still runs the whole Vitest run, marked
                                 # files included, so a marked test must skip itself without the
                                 # stack; a Vitest `exclude` of them hides them from e2e-test too.
                                 #
                                 # e2e-test runs in each declared project, as unit-test does, and
                                 # each member from its own directory
                                 # with no path, so the member's own test configuration
                                 # (pytest config, `testpaths` included) decides what is collected
      e2e_unit_scope: null      # own | full for this repo; null follows limits
      e2e_schedule: null        # daily | weekly | monthly | 'off' for this repo; null follows limits
      dev_stack_marker: dev_stack
      replay: null            # record/replay of e2e-test calls outside the stack:
                              # upstreams [{name, url, kind: deterministic|llm, env,
                              # keyed_headers}], directory (tests/cassettes),
                              # max_age_days 30, llm_max_age_days 14, max_body_bytes 2 MiB,
                              # max_directory_mb 100, review_after_runs 5
    checks:
      affected:
        mode: off             # off | profile | command: the tests the check after a failed
                              # check and a fix runs first; the full suite always confirms
                              # a pass, and every other check is full
        command: null         # `command` mode needs a template whose words
                              # `{changed_files}` and `{failed_ids}` each expand to
                              # separate arguments (a word of its own, not `--f={...}`)
    dev_stack: null           # {script: scripts/dev-stack.sh} — a script with
                              # up/test/down; e2e-test runs on it, not live
    environment: null         # the same shape as the top-level `environment`, with paths
                              # relative to the repo; run in a unit's worktree.
                              # `abk doctor` warns for a repo without one
    agent_commands: null      # commands the build prompts tell an agent it may run, each
                              # {purpose: test|lint|format|check, command: "uv run pytest -q",
                              # scope: whole|file|node-id}; `{path}` in the command exactly when
                              # the scope is not whole. null follows the profiles, a list
                              # replaces them. Each must match the build allow-list: refused at load
    changelog: CHANGELOG.md   # the repo's changelog; null = no convention, no check.
                              # Convention: AGENTS.md `## Changelog`, else CLAUDE.md,
                              # else the packaged text. Doctor warns if the file is absent
    deploy:
      needs_ssh_agent: false  # image builds that fetch a dependency over ssh
      ssh_key: null
      agent_for: [scripts/deploy.sh, scripts/deploy-blue-green.sh]
      live_written: []        # paths the running system writes; ignored when
                              # checking main is clean before a deploy
      rules: []               # first match wins; docs and tests never match
        # - prefix: service/  # a directory (trailing slash) or a file
        #   run: [[scripts/deploy.sh, service]]   # argv lists; [] = nothing
      credentials: null
        # names_from: {file: scripts/dev-stack.sh, shell_array: TEST_CREDENTIALS}
        # values_from: .env

verify:
  # Resolved in order: a list here (an override for every repo) > the repo's
  # `infra:` profile's command (docker: the container listing
  # `docker ps --format "{{.Names}}\t{{.Image}}"`; none: nothing) > nothing.
  # Leaving the key out is not `null`, which records nothing for every repo.
  # A command that cannot start is logged, not fatal. A repo that relied on the
  # old built-in default now gets `none`: name `infra: docker` to record again.
  # stack_versions_command: [docker, ps, --format, "{{.Names}}\t{{.Image}}"]
  env: {}                     # environment for the live tests, each value
                              # resolved by a provider at verify time:
    # VAR: {from: literal, value: x}
    # VAR: {from: env-file, file: /path/.env, key: KEY}
    # VAR: {from: yaml, file: /path/f.yaml, path: a.b.c, take: last-word,
    #       strip_prefix: ""}
    # VAR: {from: command, argv: [cmd, arg]}

notifications:                # tell a person when a unit waits on them
  provider: off               # off | command | windows
  delay_minutes: 10           # a card waits this long before it is shown
  remind_after_minutes: 30    # shown again this often while it stands; 0 never
  command:                    # provider `command`: argv templates, never a shell
    show: ""                  # {id} {title} {body} {link}; required for `command`
    clear: ""                 # {id} only
  # provider `windows`: toasts through the BurntToast module, pinned to 0.8.5
  # (the cmdlet names changed between releases); `abk init` offers to install it.
```

### E2e-test splits

`tests.e2e_splits` (top level, or under a repo's own `tests`, which replaces it for that
repo) maps a split name to a `marker`, an optional `hold` and an optional `gate`. `rest`, the
tests in no split, is always there and may carry `hold` or `gate` but no marker. The configuration wins over the state
file `e2e-held.json`. The three runtime lists it replaced are gone, with no alias.

`tests.e2e_dimensions` (top level, or per repo, which replaces it) maps a dimension to its values,
each with a `marker`; a marker belongs to one value or split. `tests.e2e_available` (in `abk.yaml`
or the machine-local `abk.local.yaml`) maps a dimension to the values this machine has; a dimension
with no entry has every value, and an undeclared name is refused. A run leaves out the tests of
unavailable values; a scheduled split with nothing runnable is skipped, not failed.

`abk e2e-test hold <split>` and `abk e2e-test release <split>` set and clear `hold` and the state
file entry together; `abk e2e-test status` shows what is held. A hand-set hold has no deadline.

`abk e2e-test check [repo]` lists each split and `rest` with its marker and test count, and
exits 0 when no test is in two splits, no marker is unknown to the test runner and no
listing fails; 1 for a finding or a split the profile cannot apply; 2 for an unknown repo. It runs no test.

## Which file holds what

`abk.yaml` reads the same on every machine that runs the pipeline. Ask of any line: *would this
be wrong on another person's machine?* If so it goes in `abk.local.yaml` (ignored by git, merged
over `abk.yaml` key by key), and a secret or a single per-machine value goes in `.env`.

- **`abk.yaml`**: repo names, slugs, forges, default branches, profiles, projects, deploy rules,
  test kinds and markers, split and dimension declarations, models, review settings, team policy.
- **`abk.local.yaml`**: `repos.<name>.path` and `planning.worktree_root`; `verify.env.<NAME>.file`;
  which Claude account builds a repo (`repos.<name>.account`) with each account's `config_dir`,
  `limits` and slots, and the default account's usage thresholds; `project_limits` (how many units
  this machine runs at once); `e2e_available`, split holds and
  a machine's scheduled-run `off`. A person with one Claude account sets nothing for accounts.
- **`.env`**: tokens, PATs, `ABK_*` switches, read through `from: env-file`.

`abk config --path` names the files in force and `abk config --show` prints the merged result;
check it after moving a value. `abk config --migrate` moves the machine settings of a tracked
`abk.yaml` to `abk.local.yaml` for you, and `--include-defaults` adds the defaults a team may commit.

## Where an installation's facts live

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

Both files are a person's to change. A step that was not confined fails with `ConfigChanged` if
either differs afterwards; during a confined run a person may edit them, and the difference is a
warning shown by `abk status`, not a failure.

The guards by class: the text fence on these two files is a location guard, so it stands down for
a confined step and applies to one that is not; guards about meaning (no merge, no push) apply
either way. `abk policy check` lists which is which; the table is in docs/sandbox-design.md.

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

They are independent layers, and both may be used. For a fact either could carry, the loader
reads the entry itself (which `verify.env` variable exists, and its provider) from `abk.yaml`
merged with `abk.local.yaml`, and reads that entry's value from the file its `env-file`
provider names, `.env` here. Nothing reads `.env` for the entry itself.

A planning repo that plans only itself needs no other repo entries: its own entry, with path
`.`, is the checkout naming itself.

Words that only this installation knows go in `scrub.local`, one per line (`!word` removes a
derived term); `abk scrub-check` reads it. `abk doctor`'s `public content` check warns when
`abk.local.yaml` or `scrub.local` is tracked or not ignored, and when a committed `abk.yaml`
holds a repo path outside the checkout, a home path or another account's repo.

## A sync that runs more than one command

`sync` is one argv list, run without a shell, in the top-level `environment` and
in a repo's `repos.<name>.environment` alike. An environment that needs two
installs (say `uv sync` and `npm ci` in a subfolder) writes it as a shell
command with `sh -c`, changing directory in a subshell:

```yaml
environment:
  sync: [sh, -c, "uv sync && (cd web && npm ci)"]
```

Where a tool's own directory option is not accepted (for instance
`npm ci --prefix` is not accepted), change directory in a subshell:
`(cd dir && npm ci)`.

## The Claude Code account

The account the pipeline runs `claude` on is a config directory, set in the
installation's `.env` or the process environment as `CLAUDE_CONFIG_DIR` or
`ABK_CLAUDE_HOME` (aliases of one value; `CLAUDE_CONFIG_DIR` wins within a place,
the process beats the `.env`). It is not in abk.yaml: it is per user and per
machine, and abk.yaml is committed. Unset means the default `.claude` directory
under the home directory. `abk doctor` says where the value came from and whether
the account is logged in. Steps and rules: `docs/claude-code-second-account.md`.

## What `abk doctor` checks

Each check prints `ok`, `warn` or `FAIL` with a one-line fix; the exit status
is 1 when anything failed.

| Check | Failure means |
|---|---|
| config loads | `abk.yaml` is missing, malformed or has an unknown key; or the selected runtime (`ABK_RUNTIME`, which may come from the planning repo's `.env`, else `runtime:`) is unknown, or is missing a fact it requires under `runtimes.<name>`. |
| worktree root | `planning.worktree_root` is inside the planning repo. |
| repo checkout | A repo's `path` does not exist, is not a git checkout, or has no repo-local `user.email` (commits made there would carry the wrong identity). |
| gh account | `gh auth token --user <owner>` fails for an owner in `repos`; log that account in. |
| node / openspec | `node`/`npx` are not on PATH, or the OpenSpec CLI does not run through `openspec.command`. |
| runtime | The selected runtime is not implemented, or its agent command is not on PATH. |
| runtime account | The Claude Code account directory does not exist or is not logged in; the fix is the exact `CLAUDE_CONFIG_DIR=<dir> claude auth login`. It also says which name and place supplied the directory, and warns when `CLAUDE_CODE_OAUTH_TOKEN` is set beside an account. |
| runtime coverage (warn) | The runtime sees only some of the agent's tool calls (`agent_flagged` or `none`). |
| runtime policy | The runtime does not refuse a command class abk forbids; each is named, and the fix printed is, in order, `runtimes.<name>.policy_fix`, the runtime's own advice, `abk policy apply` for an agent the kit can merge into, else `abk policy patterns` and the `policy_fix` key to set. `abk init` offers to run it, and `abk init --policy-only` runs just that step on an existing installation (with no `policy_fix` and an agent the kit can write to, init offers the kit's recommended policy, the same merge as `abk policy apply`, and an agent it cannot write to is pointed at `abk policy patterns`; `--policy-fix ARGV` records and uses a fix; with `--yes`, a configured fix or the kit's policy runs only given `--policy-fix` or `--run-policy-fix`; exit 0 passes, 1 a class is still not refused, the configuration is absent or unreadable, or the agent cannot be checked, 2 a usage problem). An entry with `policy: unchecked` warns here instead and is not checked; `doctor` also lists other usable runtimes and warns for a selected entry that is documented only. The check reads the agent's configuration (what the configuration says, in abk's dialect; not observed from the agent), starts no agent and keeps no answer; `abk policy check` runs it on demand. It fails when the configuration is absent or unreadable, naming the path or reason, and warns `cannot check: abk has no policy for this agent` for a command it does not recognise. It warns, unchecked, when the agent command does not resolve; fix the `runtime` check first. |
| telemetry (warn) | `ABK_OTEL_ENABLED` is set but there is no traces or metrics endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`, or the per-signal `..._TRACES_ENDPOINT` / `..._METRICS_ENDPOINT`), or one does not answer. Only checked when enabled. |
| ssh key | A `deploy.ssh_key` does not exist. |
| verify env | A `verify.env` provider cannot resolve (names only are reported, never values). |
| rules (info/warn) | Read from the `# abk-rules: vN` stamp at the top of `openspec/config.yaml`, never from the wording: reword the rules freely. `info` = no stamp, so nothing can be concluded; `warn` = the framework has added rules since that version (it lists them) or the stamp is newer than the framework. `abk init --update-rules` adds what they added to the end of the `context:` and restamps the file, changing nothing else. |
| abk.yaml gaps (warn) | A service directory with no deploy rule, a rule whose prefix no longer exists, a dev-stack script without `dev_stack`, or a `live_written` path that is not a directory. |
| agent commands (ok/info/FAIL/warn) | Each repo's effective `agent_commands`: ok with the count, info when none are named, FAIL for a command (a profile's own included) outside the build allow-list, warn when they would not all fit the prompt section's 600 characters. |
| review (warn/FAIL) | A protected or class glob matches no file in any repo (warn), policy is set while `review.enabled` is false (warn), or a glob does not parse (FAIL). |
| changelog (warn) | A repo's `changelog` path names a file its checkout does not have. Not checked when `changelog: null`. |
| notifications | `notifications.provider` is `windows` and `powershell.exe` does not list the pinned BurntToast version (the fix is the install command), or is `command` and the `show` program is not on PATH. Nothing is checked while the provider is `off`. |
| public content (warn) | The committed `abk.yaml` holds a repo path outside the checkout, a home-directory path in a value or a repo owned by another account than the origin (the key is named, never the value); or `abk.local.yaml`, `scrub.local` or a `*.pre-redact` copy is tracked or not ignored (the fix names the line to add). Offline. |
| skills (warn) | An installed abk skill is older than the framework; run `abk install-skills`. |

## The `review` section

`review:` holds the review policy: `enabled` (default false), `brief` (default true: a pull request body
opens with a "Start here" section; false builds the body as before and changes no verdict record), `protected_paths`, `protected_defaults`
(default true), `classes` (name to path globs, no slash in a name, first listed wins) and
`auto_land.min_samples` / `auto_land.min_clean_rate` / `auto_land.allow_deferred_e2e` (default false:
a unit whose e2e result was deferred to verify stays at `light` or above; accepted only under
`review.auto_land`), `auto_land.classes` (default empty, which turns landing without a person off; each must be named in
`classes`; once set, `abk doctor` warns for each repo with no branch protection, and when `enabled` is false), `audit.sample_rate` (default 0.1, 0 to 1), `demotion.window` (default 30, at least 1) and `demotion.min_agreement`
(default 0.9, 0 to 1), and `ceilings` (`auto` 5000, `light` 2000, `full` 750 by default: the estimated lines
a unit may carry, by its expected review tier; ordered `auto` >= `light` >= `full` > `min_unit_lines`; used only when
`review.enabled` is true, otherwise every unit is held to the `full` ceiling). A repo's `review:` holds `protected_paths`,
which adds to the workspace's, and `ceilings`, a repo override of any one tier. `global_limits.max_unit_lines` is
deprecated and read as `review.ceilings.full`; `abk config --migrate` moves it, and setting both to different values is refused.
`ceiling_buffer` (0 to 1, default 0.2: a unit is held for its size only past its tier's ceiling times one plus this) and
`split_rounds` (0 to 2, default 2: splits along a unit's lineage; 0 sends every oversized unit to a person) govern the size
hold, and the config fails to load when the buffered `auto` ceiling would reach the reviewer's reading limit of 10,000 lines.
Only a person edits it: a build agent and a track are
refused a write to `abk.yaml` or `abk.local.yaml` by the routes the command policy names, and a
build or track run after which either file differs fails (not restored). See `docs/configuration.md`.

## Changing the config

- A new repo: add it under `repos`, run `abk doctor`, then `abk install-skills
  --repo <path>`.
- A new service directory: add a `deploy.rules` entry with its prefix and
  the commands that deploy it, or an empty `run:` if nothing does.
- A contract between repos: `consumes` on the consumer, and a sentence in
  `relationships` on both sides, so the planner orders the work.

## A repo that is also the planning repo

List the repo in `abk.yaml` with the path `.`. `abk install-timers` then makes a
pipeline worktree, outside the repository, where ticks and tracks run; edit
`abk.yaml` in your working copy and let it reach the default branch. From the
working copy, commands that run the pipeline need the worktree's config:
`abk --config <worktree>/abk.yaml <command>` (`abk status` prints it).
`planning.publish` decides where a track's planning commit goes: `direct` pushes
it to the default branch, `branch` pushes it to a `planning/...` branch and opens
a pull request, which suits a protected branch. `abk doctor` fails `direct` where
the default branch is protected.
