# Configuration

Two files configure an installation, and they answer different questions.

- **`abk.yaml`**, in the planning repo, committed and reviewed: everything
  that describes *this workspace* — which repos, where they are checked out,
  which host each lives on, how each deploys and tests, what the planner should
  know about how they relate, the limits and models. The schema is strict
  (`extra="forbid"`): a misspelled key fails at load, not later.
- **`.env`**, in the planning repo, ignored by git: what differs *per machine*
  or must not be committed — a token, a worktree root override, a model
  override, the OpenSpec version pin.

**Installation facts live here.** The framework knows nothing about any
particular installation; a fact that belongs to one (a path, an owner, a
deploy command, a credential name) is a field in `abk.yaml` with a default,
never a constant in code, a prompt or a skill.

## Locating `abk.yaml`

In order: `abk --config PATH`, then `ABK_CONFIG` in the environment, then the
nearest `abk.yaml` walking up from the working directory. The file's
directory is the **planning root**; every relative path in the file is
relative to it. Commands that need an installation exit 2 when none is found.

`abk config --path` prints the file in force; `abk config --show` (the
default) prints the effective configuration with every default filled in.
`abk doctor` checks the installation is runnable — see [cli.md](cli.md).

## `abk.yaml` reference

Every field, with its default. A key at its default can be left out;
`abk init` writes only what differs from the defaults.

```yaml
version: 1

planning:
  state_dir: runs               # pipeline state, run logs, each tier 2 run's full
                                # output (tier2-output/) and the usage ledger
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
  self_pull: true               # the tracks pull the planning repo's default
                                # branch before running.

openspec:
  command: null                 # argv for the OpenSpec CLI. null = npx --yes
                                # @fission-ai/openspec@<ABK_OPENSPEC_VERSION>.

retention:
  decision_log_mb: 50           # decisions.jsonl is trimmed to this size, newest lines kept
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
      weekly:                   # the same settings, for the week
        usage_pause_pct: 70
        usage_pause_ceiling_pct:
        usage_relief_fraction: 0.25
        usage_resume_buffer_pct: 5
        usage_unit_allowance_pct: auto  # as above
        usage_allowance_floor_pct: 1
      calibrate_usage_allowances: true  # false: every window uses its configured allowance
      usage_allowance_quantile: 0.9     # the quantile of points gained per unit (above 0, at most 1)
      usage_allowance_window: 30        # newest usable pairs of readings it is taken over
      usage_allowance_min_pairs: 8      # fewer pairs than this and the configured allowance stands
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
  #   models: {implement: "..."}          # only when a second runtime's model
  #                                       # names must coexist with the block
  #                                       # below

models:                         # bare aliases, not pinned ids. These are the
                                # ACTIVE runtime's models; a runtimes.<name>.
                                # models block overrides them when present,
                                # and a role left out of both takes the
                                # runtime's own default (these, on claude_code).
  implement: sonnet             # the tests, implementation and check-fix runs
  rework: sonnet                # reworks, restack conflict resolution, adapt, when they
                                # start a new session; a continued build session
                                # keeps its model
  review: opus                  # the first review of a fresh build
  rework_review: opus           # every review of a rework. Both reviews default
                                # to a different model from the author's; if the
                                # author is set to opus, set this to another

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
# It runs in the unit's worktree: before the tests and every tier 1, `sync` runs
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

limits:
  stack_depth_build_cap: 3      # longest chain of in-review PRs from main a
                                # new unit may extend
  stack_depth_rebase_cap:       # deepest a dependent may sit when a merge
                                # restacks it; unset = the build cap's value
  max_concurrent_stacks: 4      # units being built at once, across all repos
  max_concurrent_restacks: 2    # restacks (a branch moved onto a changed base) at once; they take no build slot
  max_flakes_per_run: 5         # more tests than this failing a run's first pass and passing
                                # alone is one recorded storm, no fix change per test
  checks_register_seconds: 120  # seconds after a push in which a pull request with no
                                # checks yet still reads `checking`
  label_sweep_per_tick: 20      # finished units' pull requests whose stale state
                                # label a round takes off (each tick and each
                                # refresh of a pass), at least 1
  max_units_in_progress: 5      # units started and not finished, across all
                                # repos, at least 1; at it no unit that has
                                # never started does, while reworks, resumes
                                # and finishing reviewed work still run; a
                                # blocked unit, and a failed unit that waits
                                # on another unit, do not count
  min_unit_lines: 400           # estimated changed lines before the planner
                                # stops absorbing the next task group
  max_unit_lines: 750           # estimated changed lines one unit may carry;
                                # must exceed min_unit_lines. Shapes plans;
                                # a unit that lands over it is logged and
                                # listed by `abk status`, never blocked
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
  tier1_command_seconds: 3600       # longest a tier 1 command may run before it is aborted
  tier1_abort_grace_seconds: 10    # how long an aborted command has to exit before it is killed
  tier1_repeat_runs: 3              # times the tests a unit added or changed are run again under load (0: off)
  restack_check: affected           # tier 1 after a clean move: scoped by the files the move brought in (affected) or the whole suite (full); a scoped move runs the unit's own tests and the profile's selection, and the profile selects only where `checks.affected` records data
  tier2_base_runs: 1                # run the untouched failed tier 2 tests once on the base (0: off)
  tier2_unit_scope: own             # tier 2 per unit: only the tests it added or changed (own) or the whole marker (full); tests.tier2_unit_scope overrides per repo
  tier2_lock_wait_seconds: 5400     # longest post-merge verification waits for the tier 2 lock before reporting it busy
  tier2_durations_shown: 15         # slowest tier 2 test entries the posted result lists (0 = all)
  network_probe_timeout_seconds: 5  # longest the outage probe waits to connect to one host
  network_control_hosts: [one.one.one.one, dns.google]  # bare host names tried beside the code hosts to tell a network outage from a model service outage
  service_unavailable_attempts: 5   # times in a row a 5xx or 529 from the model service parks a unit before the next fails it

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
    path: /srv/src/platform     # the checkout (~ is expanded)
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
    profile: python-uv          # toolchain profile: python-uv, or node-npm
                                # (declared, not implemented). The repo-wide
                                # default; a project below may set its own.
    infra: none                 # infrastructure profile: docker or none
                                # (infra/). What the repo runs on, apart from
                                # its language; `docker` records the container
                                # listing beside a tier-2 result, `none`
                                # (the default) records nothing. `abk init`
                                # writes `docker` when the root has a compose
                                # file or Dockerfile. An unknown name fails
                                # when abk.yaml loads.
    projects: []                # where each project inside the repo lives, so
                                # tier 1 runs its checks *inside* it:
                                #   - path: services/api
                                #     languages: [python]
                                #     profile: python-uv
                                # A file belongs to the deepest project holding
                                # it. Left empty, checks run at the repo root —
                                # which fails outright when the repo root is not
                                # a project (`uv run pre-commit` cannot resolve
                                # pre-commit there). Written by `abk init`.
                                # A project whose directory does not exist in
                                # the checkout being checked is *pending*: tier
                                # 1 and tier 2 run nothing in it and name it in
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
      tier2_marker: local_stack # the pytest marker on tests needing the real
                                # stack (tier 2, and post-merge verify)
      dev_stack_marker: dev_stack
                                # the marker on tier-2 tests only the dev stack
                                # can run; left out of post-merge verify
      replay: null              # record and replay of the calls tier-2 tests make outside
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
                                # the project directory under the tier 1 time limit;
                                # the profile's "no tests collected" exit counts as
                                # a pass, and the full run still confirms it
    dev_stack: null             # {script: scripts/dev-stack.sh}: a script with
                                # `up`, `test` and `down`. Tier 2 runs the
                                # unit's branch on it instead of the live
                                # stack. null = no dev stack.
    changelog: CHANGELOG.md     # where the repo keeps its changelog. Set, the
                                # build, rework, resolver and review prompts
                                # carry its convention and tier 1 runs
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
                                # recorded beside a tier-2 result so a
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
                                # a unit's tier 2 and the check after a merge
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

### `redact`

`redact: [NAME, ...]` lists environment variables whose values are secrets the framework
has no field for. Each value is read from the process environment and the planning root's
`.env`, and is replaced by `[redacted:NAME]` wherever the pipeline stores or sends text,
as the `verify.env` values and the credential settings are. A value under 8 characters is
not replaced, and `abk doctor` warns, by name, for such a variable and for a name that is
not set. See "Secrets never leave as text" in `docs/architecture.md`.

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
| `ABK_REPLAY_MODE` | what tier-2 tests do with the calls they make outside the stack: `off` (no listener, nothing changed), `record` (all live, a passing test's calls are written), `replay` (an exact, fresh match answers from its cassette; anything else goes live and is recorded) or `live` (cassettes ignored, recordings written as in `record`). Any other value is refused | `off` |
| `ABK_FORGE_TIMEOUT_SECONDS` | the timeout on every call to a code host | `30` |
| `ABK_FORGE_RETRIES` | how many times a failed code-host call is retried after the first attempt | `3` |
| `ABK_FORGE_DEADLINE_SECONDS` | the most time, from a code-host call's first attempt, that retries and their waits may take | `120` |
| `ABK_WORKTREE_ROOT` | overrides `planning.worktree_root` on this machine | unset |
| `ABK_OPENSPEC_VERSION` | the `@fission-ai/openspec` version run through `npx`; a pin, so an upgrade is a deliberate change | `1.13.1` |
| `ABK_RUNTIME` | overrides `runtime` on this machine, so a runtime can be tried on one invocation without moving every repo in the workspace | unset: the file's |
| `ABK_IMPLEMENT_MODEL`, `ABK_REWORK_MODEL`, `ABK_REVIEW_MODEL`, `ABK_REWORK_REVIEW_MODEL` | per-machine overrides of `models.*` | unset: the file's |
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
