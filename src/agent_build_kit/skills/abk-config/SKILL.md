---
name: abk-config
description: TRIGGER — read before editing abk.yaml in a planning repo, when `abk doctor` reports a problem, or when asked where an installation fact (a repo path, a GitHub owner, a deploy command, a credential name) should live. SKIP for questions about running the pipeline (abk-pipeline) or writing a change's tasks (abk-authoring).
version: 1.0.0
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
Enterprise host needs `GH_TOKEN` too), the telemetry switch `ABK_OTEL_ENABLED` and its
`OTEL_*` endpoints, and `ABK_GRAFANA_URL`/`ABK_GRAFANA_TOKEN`/`ABK_GRAFANA_FOLDER`
for `abk telemetry push-dashboard`, whose token is optional: without it the push is
anonymous) go in the planning repo's `.env`, which is not
committed.

The schema is strict: an unknown key fails at load. `abk config --show`
prints the effective config with every default filled in; `abk config
--path` prints which file is in force (`--config`, then `ABK_CONFIG`, then
the nearest `abk.yaml` above the working directory).

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
    limits:                   # with the same settings
      session:                # the 5-hour window
        usage_pause_pct: 70            # % at which no unit starts
        usage_pause_ceiling_pct:       # what that rises to at the reset; unset =
                                       # usage_pause_pct, which means no ramp
        usage_relief_fraction: 0.25    # trailing part of the window a ramp spans
        usage_resume_buffer_pct: 5     # room above usage a resume waits for
      weekly:                 # the 7-day window: the same four
        usage_pause_pct: 70
        usage_pause_ceiling_pct:
        usage_relief_fraction: 0.25
        usage_resume_buffer_pct: 5
  # <name>:
  #   command: [some-agent, acp]          # argv that starts its agent
  #   policy_fix: [scripts/constrain.sh]  # offered by init, printed by doctor
  #   models: {review: "..."}             # this runtime's names for roles;
  #                                       # a role left out keeps models:'s

models:                       # bare aliases, not pinned ids; ABK_*_MODEL
                              # overrides win over these and runtimes' own.
                              # A role named nowhere takes the active
                              # runtime's own default (these, on claude_code)
  implement: opus
  rework: opus
  review: opus
  rework_review: fable        # a different model reviews a rework

session_reuse:                # per agent role: continue the role's latest session
  build: true                 # tests/implement/fix/rework/adapt share one session
  review: false               # always false: a review starts fresh; a role left out is off

limits:
  stack_depth_build_cap: 3    # longest chain of in-review PRs from main
  stack_depth_rebase_cap:     # deepest a merge restacks a dependent; unset = the build cap
  max_concurrent_stacks: 4    # units implemented at once, across repos
  max_units_in_progress: 5    # started, unfinished units (>= 1); at it no never-started unit starts
  min_unit_lines: 400         # estimated lines before a unit stops growing
  max_unit_lines: 750         # estimated lines one unit may carry; above
                              # min_unit_lines. Shapes plans; a unit landing
                              # over it is reported, never blocked
  generated_files: [uv.lock, ...]  # patterns left out of a unit's actual size
  max_review_rounds: 3        # review rounds before a unit fails
  max_check_rounds: 3         # fix rounds for failing checks, per review round; null = no limit; 0 = none (still checked)
  max_adapt_rounds: 2         # adapt-step accounting asks, first included,
                              # before a unit fails
  max_plan_attempts: 3        # times one tasks.md is sent to the planner
  max_check_reruns: 2         # re-runs of a head commit's cancelled checks

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
                              # records the container listing beside a tier 2
                              # result (init writes it when a compose file or
                              # Dockerfile is in the root)
    languages: []             # e.g. [python]
    description: ""           # one paragraph, for prompts and context
    consumes: []              # repos this one depends on: deploy order,
                              # which dev stack it comes up on, planning order
    relationships: ""         # prose for the planner about the other repos
    tests:
      root_extras: []         # extra packages the repo-root tests need
      tier2_marker: local_stack  # tier 2 runs in each declared project, as tier 1 does, and
                                 # each member from its own directory
                                 # with no path, so the member's pytest config,
                                 # `testpaths` included, decides what is collected
      dev_stack_marker: dev_stack
    dev_stack: null           # {script: scripts/dev-stack.sh} — a script with
                              # up/test/down; tier 2 runs on it, not live
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
```

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
| runtime coverage (warn) | The runtime sees only some of the agent's tool calls (`agent_flagged` or `none`). |
| runtime policy | The runtime does not refuse a command class abk forbids; each is named, and the fix printed is `runtimes.<name>.policy_fix`. `abk init` offers to run it. The answer is reused for 15 minutes. It also fails when the check could not be run because the runtime raised (e.g. its usage window is spent); nothing is cached, so run doctor again once the runtime can answer. It warns, unchecked, when the agent command does not resolve; fix the `runtime` check first. |
| telemetry (warn) | `ABK_OTEL_ENABLED` is set but there is no traces or metrics endpoint (`OTEL_EXPORTER_OTLP_ENDPOINT`, or the per-signal `..._TRACES_ENDPOINT` / `..._METRICS_ENDPOINT`), or one does not answer. Only checked when enabled. |
| ssh key | A `deploy.ssh_key` does not exist. |
| verify env | A `verify.env` provider cannot resolve (names only are reported, never values). |
| rules (info/warn) | Read from the `# abk-rules: vN` stamp at the top of `openspec/config.yaml`, never from the wording: reword the rules freely. `info` = no stamp, so nothing can be concluded; `warn` = the framework has added rules since that version (it lists them) or the stamp is newer than the framework. `abk init --update-rules` adds what they added to the end of the `context:` and restamps the file, changing nothing else. |
| abk.yaml gaps (warn) | A service directory with no deploy rule, a rule whose prefix no longer exists, a dev-stack script without `dev_stack`, or a `live_written` path that is not a directory. |
| changelog (warn) | A repo's `changelog` path names a file its checkout does not have. Not checked when `changelog: null`. |
| skills (warn) | An installed abk skill is older than the framework; run `abk install-skills`. |

## Changing the config

- A new repo: add it under `repos`, run `abk doctor`, then `abk install-skills
  --repo <path>`.
- A new service directory: add a `deploy.rules` entry with its prefix and
  the commands that deploy it, or an empty `run:` if nothing does.
- A contract between repos: `consumes` on the consumer, and a sentence in
  `relationships` on both sides, so the planner orders the work.
