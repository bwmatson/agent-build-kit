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
  state_dir: runs               # pipeline state and run logs. Relative to the
                                # planning root unless absolute.
  specs_dir: openspec           # the OpenSpec store; changes are read from
                                # <specs_dir>/changes/*/tasks.md.
  graph_page: docs/unit_graph.md
                                # the mermaid unit graph, rewritten on every
                                # state change.
  worktree_root: null           # where per-unit worktrees are checked out:
                                # <root>/<repo dir name>/<branch>. Never inside
                                # the planning repo (refused at load). null =
                                # ~/.local/share/<planning dir name>/worktrees.
  self_pull: true               # the tracks pull the planning repo's default
                                # branch before running.

openspec:
  command: null                 # argv for the OpenSpec CLI. null = npx --yes
                                # @fission-ai/openspec@<ABK_OPENSPEC_VERSION>.

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
      weekly:                   # the same four settings, for the week
        usage_pause_pct: 70
        usage_pause_ceiling_pct:
        usage_relief_fraction: 0.25
        usage_resume_buffer_pct: 5
  # acp:                        # an agent speaking the Agent Client Protocol
  #   command: [some-agent, acp]          # how to spawn it
  #   policy_fix: [scripts/constrain.sh]  # what `abk init` offers to run when
  #                                       # the agent does not refuse what the
  #                                       # command policy forbids
  #   models: {implement: "..."}          # only when a second runtime's model
  #                                       # names must coexist with the block
  #                                       # below

models:                         # bare aliases, not pinned ids. These are the
                                # ACTIVE runtime's models; a runtimes.<name>.
                                # models block overrides them when present,
                                # and a role left out of both takes the
                                # runtime's own default (these, on claude_code).
  implement: opus               # the tests and implementation runs
  rework: opus                  # reworks, restack conflict resolution, adapt
  review: opus                  # the first review of a fresh build
  rework_review: fable          # every review of a rework: a different model
                                # from the one that made the edit

limits:
  stack_depth_build_cap: 3      # longest chain of in-review PRs from main a
                                # new unit may extend
  stack_depth_rebase_cap:       # deepest a dependent may sit when a merge
                                # restacks it; unset = the build cap's value
  max_concurrent_stacks: 4      # units being built at once, across all repos
  max_units_in_progress: 5      # units started and not finished, across all
                                # repos, at least 1; at it no unit that has
                                # never started does, while reworks, resumes
                                # and finishing reviewed work still run
  min_unit_lines: 500           # estimated changed lines before the planner
                                # stops absorbing the next task group
  max_unit_lines: 1000          # estimated changed lines one unit may carry;
                                # must exceed min_unit_lines. Shapes plans
                                # only — a branch is not measured against it
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
  raw_output_dir: .last-runs    # each phase's raw `claude -p` JSON, relative
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
    dev_stack: null             # {script: scripts/dev-stack.sh}: a script with
                                # `up`, `test` and `down`. Tier 2 runs the
                                # unit's branch on it instead of the live
                                # stack. null = no dev stack.
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
  stack_versions_command:       # recorded beside a tier-2 result so a
    [docker, ps, --format, "{{.Names}}\t{{.Image}}"]
                                # reviewer can see what the stack was; one
                                # `name<TAB>image` per line. null = record
                                # nothing.
  env: {}                       # environment handed to the live-stack tests —
                                # a unit's tier 2 and the check after a merge
                                # alike — each value resolved by a provider
                                # when the run starts (below)
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

## Environment variables and `.env`

`settings.py` reads these with pydantic-settings: from the process
environment, and from the planning root's `.env` once the installation is
loaded (`abk init` writes `.env.example` to copy).

| Variable | Meaning | Default |
|---|---|---|
| `ABK_CONFIG` | the `abk.yaml` to use, when it is not the nearest one above the working directory | unset |
| `GH_TOKEN` (or `ABK_GH_TOKEN`) | one GitHub token for every `gh` call, instead of the per-owner lookup `gh auth token --user <owner>`. Read from `.env`, since pydantic-settings does not export to the environment and a bare `GH_TOKEN=` there would never reach a subprocess otherwise. | unset: per-owner lookup |
| `ABK_WORKTREE_ROOT` | overrides `planning.worktree_root` on this machine | unset |
| `ABK_OPENSPEC_VERSION` | the `@fission-ai/openspec` version run through `npx`; a pin, so an upgrade is a deliberate change | `1.13.1` |
| `ABK_RUNTIME` | overrides `runtime` on this machine, so a runtime can be tried on one invocation without moving every repo in the workspace | unset: the file's |
| `ABK_IMPLEMENT_MODEL`, `ABK_REWORK_MODEL`, `ABK_REVIEW_MODEL`, `ABK_REWORK_REVIEW_MODEL` | per-machine overrides of `models.*` | unset: the file's |
| `ABK_OTEL_ENABLED` | the one switch for telemetry (traces and metrics, see `telemetry.py`); nothing OpenTelemetry is imported while it is false. Needs the `telemetry` extra (`pip install agent-build-kit[telemetry]`); without it one line says so and the run carries on | `false` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | the OTLP/HTTP collector base URL; `/v1/traces` and `/v1/metrics` are appended | unset |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | per-signal full URLs, overriding the shared endpoint (traces and metrics usually have different intake ports) | unset |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | passed to the resource (`k=v,k2=v2`) | `agent-build-kit`, unset |

A bad collector cannot fail or slow a run: exports are batched, a failure is
at most a warning, and `shutdown()` is bounded. `abk doctor` warns when
telemetry is enabled with no endpoint or one that does not answer.

The model overrides name the *active* runtime's models: a role's model is
resolved against whichever runtime is selected, so an override naming a model
one runtime knows and another does not applies only while that runtime is in
force. See [agent-runtimes.md](agent-runtimes.md).

Two more are read outside the settings layer because they belong to Claude
Code: `CLAUDE_CODE_OAUTH_TOKEN`, used by the usage guard ahead of the token
Claude Code stores under `~/.claude`, and Claude Code's own cache in
`~/.claude.json`, the fallback usage reading.

## Reaching the config from code

`Installation` (`installation.py`) loads the file and derives every path from
it: `state_dir`, `specs_dir`, `changes_dir`, `graph_page`, `worktree_root`,
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
