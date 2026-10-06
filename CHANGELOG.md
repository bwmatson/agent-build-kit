# Changelog

## Unreleased

- A tier-2 acceptance run for telemetry: `tests/integration/test_telemetry_stack.py` ticks a fixture
  unit with telemetry on and finds its trace by unit id and its `abk.unit.duration` and
  `abk.step.duration` series, without a unit id, in the shared stack's stores; with the endpoint
  pointing at nothing the tick still finishes and writes nothing. It needs the stack's dev
  instance up and the four `ABK_ACCEPTANCE_*` endpoint variables set (docs/agent-runtimes.md).

- `abk telemetry push-dashboard` pushes the framework's Grafana dashboard (shipped as package
  data, querying only metrics the telemetry module emits) to the Grafana named by
  `ABK_GRAFANA_URL` and `ABK_GRAFANA_TOKEN`, into the folder `ABK_GRAFANA_FOLDER` (default
  `agent-build-kit`). It is idempotent: the folder is created if missing and the dashboard is
  overwritten.

- Infrastructure profiles (`infra/`), a second profile kind beside the toolchain profiles: a repo
  names one with `infra:` (`docker` or `none`, default `none`; an unknown name fails when
  `abk.yaml` loads) and `abk init` writes `docker` when the repo root has a compose file or a
  `Dockerfile`. The stack-versions command resolves as `verify.stack_versions_command` when a
  list, else the repo's infra profile's, with an explicit `null` recording nothing. **Behaviour
  change:** the key no longer defaults to the `docker ps` listing, so a repo that does not name
  `infra: docker` stops recording the stack in PR bodies; add `infra: docker` to each repo (or
  re-run `abk init`), or set `verify.stack_versions_command` to the old listing to keep it. A
  stack-versions command that cannot start (missing executable, no permission) is logged and
  records nothing instead of failing the unit.

- Tier 2 runs each workspace member from its own directory with no collection path
  (`uv run --directory <member> ... pytest -m <marker> -v`), so the member's own `testpaths`
  decides what is collected.

- A usage ledger: each agent call of a unit's graph appends a line to
  `<state_dir>/usage-ledger.jsonl` (gitignored by the template) with where it was made, the
  runtime, model, session and the figures it reported, each marked by `usage_source`. Claude
  Code's result event and an `acp` agent's response usage and `usage_update` cost are read; a call
  ended by a usage limit is recorded too. A write that fails never affects a run and is reported
  once. `AgentRequest` gains `on_result`; `AgentResult` gains `usage`, `cost_usd`, `duration_ms`,
  `session_id` and `usage_source`, and its `tokens` is now derived from `usage`, so the `acp`
  runtime reports tokens too. See docs/architecture.md.

- Gateway usage attribution: with `ABK_GATEWAY_URL` and `ABK_GATEWAY_MASTER_KEY` set, each agent
  call of a unit's graph runs on a gateway key of its own (alias `abk:<unit>:<node>:<round>:...`,
  handed over in `ABK_GATEWAY_KEY`), the totals the gateway logged for it are recorded in the
  usage ledger with `usage_source` `gateway`, and the agent's own report is kept beside them
  (`reported`, `reported_cost_usd`). The key is revoked however the call ends; any gateway
  failure falls back to the agent's figures with one warning. `AgentRequest` gains `env` (added
  to an `acp` agent's environment). Spend rows are waited for up to `ABK_GATEWAY_SETTLE_SECONDS`
  (30) and until they have stopped growing for `ABK_GATEWAY_QUIET_SECONDS` (10), since a gateway
  writes its logs in batches.

- A task group can say `Independent: <reason>` to be built without waiting for the groups before
  it. Its unit has no dependency, the chain closes around it, it is never joined into a
  neighbouring unit, and `[acceptance]`/`[narrow]` units depend on every earlier unit. `abk tags`
  rejects the line with no reason, on group 1, or beside a flag. A change without the line plans
  as before.

- Telemetry for the shape of a run, when `ABK_OTEL_ENABLED` is set: a tick is a `tick` span, each unit
  run a `unit` span below it (a unit that runs again links to its earlier trace, kept on the stored
  unit as `trace`), each graph step a span with its round, and each agent call an `agent` span with
  runtime, model, role, turns and outcome. The metrics are the tick, unit and step durations,
  review rounds, check failures by kind, agent turns and tokens, usage pauses, reclaimed units and
  a gauge of units by state; none carries a unit id or change name, and no span or metric carries a
  prompt, diff, feedback or commit message. A tick flushes before it returns. `AgentResult` gains
  `turns` and `tokens`. See docs/architecture.md.

- Removing `agent-hold` releases the unit. The poller dispatches a new `release` event, and a unit
  the label held returns to `in_review` with its thread resumed. The stored unit records why it was
  held (`held_by`, absent in older records): a hold the review loop, a depth cap or the toolchain
  made stays, and the log says so. A comment or failing check that arrived during the hold is
  delivered by the next poll.

- A cancelled check is no longer a failing one. A host cancels a check when a runner never came or
  a newer run superseded it, which says nothing about the commit, yet it sent the unit back for
  rework. `PullRequest` gains `cancelled_checks` (GitHub `CANCELLED`; an Azure DevOps build policy
  whose build ended `canceled`), the poller dispatches a new `rerun_checks` event, and the forge's
  new `rerun_checks` operation runs them again with no agent, up to `limits.max_check_reruns`
  (default 2) per head commit, counted on the stored unit. `FAILURE` and `TIMED_OUT` still rework.

- The lock owns the Python tool versions. This repo's ruff and pyrefly hooks are `repo: local`
  hooks running `uv run --frozen`, with no `rev` and no interpreter-path argument, so the locked
  version is the one tier 1, CI and the editor run. `abk doctor` warns when a tool is pinned in
  both the dependency group and a hook `rev`, and when a `language: system` hook runs a tool the
  group does not hold. The Python recommendations seed describes the arrangement.

- Tier 1 type-checks `tests` in a unit's worktree. The pre-commit hook pinned pyrefly 1.2.0, which
  dropped the `tests` include in a worktree under the pipeline's state directory, so a unit's
  checks passed on test files CI then failed. The hook and the dev pin are 1.3.1.

- `poe test` and CI run the suite with `pytest-xdist` (a new dev dependency): a parallel pass in
  up to 8 workers, then a serial pass of tests carrying the new `serial` marker. A single
  `pytest <file>` still runs in one process. The python-uv profile's tier 1 does the same for a
  repo that declares `pytest-xdist` (and treats "no tests collected" in the serial pass as a pass);
  a repo without it keeps `uv run pytest -q`.

- A branch the host rewrote to different commits holding the same change, or holds at an older
  restack of the same work, is no longer refused at the push: its head is recorded as the last push,
  the approval stands, and the approved head goes out leased on it. The commits replayed over a
  host head are those made since the last push, chosen by patch with `git cherry` when a restack
  has left the branch off its last push. A host change that does not combine with
  local work still stops the unit with `StaleRemote`.

- A comment left on a held unit's pull request is no longer lost: the poller keeps it new until the
  unit takes it, so releasing the unit delivers it as a rework. A comment on a satisfied unit or a
  pull request with no unit is still consumed. The "held, ignoring" line is logged once, not every poll.

- The review after a rework of a person's comments is shown those comments, quoted as the
  reviewer's words and not instructions, each with the builder's reply (or "no reply"). The review
  may now read its pull request through the forge's read commands, and nothing that writes.

- Contributor conventions moved to `AGENTS.md`, with `CLAUDE.md` loading it, and now say that
  code changes go through the spec process, not ad hoc sessions (docs and supporting files may still
  be edited in a session).

- Runs on the Claude Code runtime no longer add its `Co-Authored-By` trailer to commits or its
  "Generated with" line to pull requests. Every run passes `attribution` empty in its
  `--settings` (and `includeCoAuthoredBy: false` for an older CLI). A repo that forbids the
  trailer used to hold the unit for a person to rewrite the commits, since an agent cannot.

- The Python recommendations seed prefers `enum.StrEnum` over repeated string literals for
  closed sets of strings on Python 3.11 and later, so `abk init`'s research proposes it.

- The unit graph is the only engine. A unit waiting for review or held waits in an interrupt of
  its thread that holds no branch lock, the poller's events and `abk requeue` resume the thread as
  commands, a usage refusal interrupts the thread before an agent step, and a run killed mid-node
  is resumed at that node. An agent runtime declares `supports_session_resume`; Claude Code's does
  (`--resume`), so a node killed mid-agent continues its session. A tick starts a unit's thread
  and resumes the ones a kill or a usage pause left; an event for a thread whose node is running,
  or held by another process's branch lock, is kept for a later poll.

- Units in flight are moved onto threads on the first tick after the upgrade: each is positioned
  at the node its stored `resume_from` step names, carrying the review rounds, deferred follow-ups,
  pending replies and the comments they answer an old store held, and a `running` unit with no
  thread starts at `prepare`. The conversion runs on every tick but only seeds a unit that has no
  thread. An old `units.json` still loads: its in-run keys are gathered into `classic_run` and
  moved to the thread, then cleared. `approved` and `predecessor_note` stay in the store, since
  the push gate and the restack write them with no run in progress. The first run of a converted
  unit skips `prepare`'s fetch and restack onto a moved base; a base moved before the upgrade is
  caught at `verify_base`.

- A killed run is resumed from its thread by the next tick, not reclaimed: `reclaim_stale`, the
  classic engine's `UnitRunner.run`, `checkpoint()` and `record_step` are gone, and so is the `wip:`
  commit of a killed run's leftovers. A usage pause leaves the unit `running`, with its thread
  interrupted before the agent node, until a tick the usage guard allows; it is no longer set back
  to `planned` with a `paused before <step>` note. A planned unit counts as started when a run
  recorded a branch, a pushed or approved commit or a pull request, not a resume step.

- New runtime dependencies: `langgraph`, `langgraph-checkpoint`,
  `langgraph-checkpoint-sqlite` and `aiosqlite`, for the unit graph. There is no setting that
  chooses an engine: `ABK_ENGINE` was never released and does not exist.

- A unit's approval now carries across a clean rebase when the base had edited lines near
  its change. The change's id was taken over its context lines too, so a parent that touched a
  line three lines away gave the same change a new id; the approval did not carry, and the unit
  was failed at the push ("refusing to push … review approved …") for a branch review had in
  effect read. The id covers only the changed lines. And a clean move whose approval does not
  carry is read again by review instead of refused.

- A rework sent back for a failing check is told how to reproduce it, from the repo's own
  toolchain (`uv run pre-commit run --all-files` for a Python repo, then the tests), on every
  host. It used to depend on the host's log: GitHub had none for a run still going and Azure
  DevOps only ever gives a status and a link. The unit's run log also records each command
  tier 1 ran, where, and how it ended, so a pass that CI then contradicts can be explained.

- A rework sent back for a failing check now gets the failure even when the run
  is still going. The poller reports a check the moment it fails, usually
  while the run's other jobs are running, and `gh run view --log-failed` has no
  log for such a run, so the rework was handed an empty block. The failed job's
  own log is fetched instead, up to its `##[error]` line; with no log at all the
  rework is told that, and to run `pre-commit run --all-files`.

- `abk init --update-rules` brings `openspec/config.yaml` up to the framework's rules
  version without rewriting it: each newer version's paragraph goes at the end of the
  `context:`, the `# abk-rules:` stamp is raised, and nothing else changes. `abk doctor`
  names it when the stamp is behind.

- **Breaking:** three more compatibility shims are removed.
  - The `github:` section of `abk.yaml` is no longer read as `git:`, and
    `abk doctor` no longer asks for the rename; a file that still has it is
    refused at load like any unknown key.
  - `limits.stack_depth_cap` is refused with the schema's usual unknown-key
    error instead of one naming `stack_depth_build_cap`.
  - A units store or PR poll snapshot written by an older version is no longer
    translated on read: the `open` unit state (now `in_review`) and the poll
    snapshot's earlier shape (`merged: true`, `CHANGES_REQUESTED`). Both are
    state files that older code wrote; let the old version finish its work
    first if one might still hold either.

- **Breaking:** the `limits.usage_pause_pct`, `usage_ceiling_pct`,
  `usage_relief_fraction` and `usage_resume_buffer_pct` keys are no longer read
  as the Claude runtime's thresholds, and `abk doctor` no longer warns about
  them. Set them per window under `runtimes.claude_code.limits` (`session` and
  `weekly`, with `usage_pause_ceiling_pct` for the ceiling); a file that still
  has them is refused at load.

- A held unit no longer counts against `limits.max_units_in_progress`: holding sets
  a unit aside until a person releases it, and it should not keep new work from
  starting. It counts again once requeued and started.

- What an agent may run to read its PR comes from its repo's forge
  (`read_commands`), so an Azure DevOps agent can read its PR with `az repos pr
  show` and is no longer offered `gh`. The tracks' default allow-list carries
  every forge's read commands in place of `Bash(gh pr *)`. An Azure DevOps poll
  reads each open PR's conversation and checks on a pool of four. The `github:`
  section of `abk.yaml` is now `git:`; the old name still loads with a warning
  and `abk doctor` asks for the rename. It stops loading in the release after
  this one. `RUN_URL`, `LOG_PREFIX` and `CHECK_LOG_CHARS` are gone from
  `pipeline/events.py`.

- A pass refreshes from the code host every five minutes while builds run, not
  only when one finishes, and starts again a unit it already built that a poll
  sent back (a conflict, a failing check, a review comment), at most twice per
  pass. A pass with one long build used to hear nothing until it ended, and the
  timer cannot start another tick while one is running.

- A usage pause lasts until the guard's own answer — the moment the ramp towards
  a window's reset offers room — instead of until the reset, and it ends on the
  first tick the guard allows: a paused tick asks again rather than sleeping to
  its deadline, so a threshold raised by hand takes effect at once. A pause no
  longer schedules a transient systemd resume; the tick timer is the resume. A
  rate-limit refusal from the model is still kept to its deadline.

- A unit fetches its repo before it restacks and again before it pushes, asks
  the forge whether its parent merged (recording a merge the store missed) and
  moves onto the base as it now is. The move before a push never runs the
  conflict resolver: a conflict, or a tier 1 or tier 2 failure on the moved
  commit, resumes the unit at its restack in the same run, once, where
  resolution runs under the usage gate and review is told of it (a second such
  hold is left planned for the next tick). A pull request refused for a missing
  base asks the forge for the base again, so a parent that merged meanwhile
  gives its merged-to branch, and resumes from that; each forge recognises its
  own error for that.

- A pull request event is matched to its unit by repo and number, not by number
  alone. Once two repos in a workspace had reached the same number, a merge,
  comment, hold or close in one was applied to the other's unit: the merge went
  unrecorded, what was stacked on it was never moved, and a finished unit could
  be requeued for feedback that was not its own.

- Each unit run writes a file of its own under `<state_dir>/unit-logs/`, named
  for the unit, its start (UTC) and the step; the unit's record names the
  latest (`run_log`). The last three runs of a unit are kept and archiving a
  change removes them. Gitignored; an existing installation adds
  `runs/unit-logs/` to its `.gitignore`.

- New `limits.max_units_in_progress` (default 5, at least 1) caps the units
  started and not finished across all repos, whether or not they have a pull
  request: running, in review, held, failed, or planned with a pull request or
  a step to resume from. At the limit no unit that has never started does: it
  stays `planned`, and the tick log and `abk status` say "queue is full: N
  units in progress, limit M" with the count in each state. Reworks, resumes,
  restacks, further review rounds and PR opening continue, so the count can go
  past the limit. Free slots go to units with an open PR first, then resuming
  builds, then new units. **Behaviour change:** installations that were
  unbounded now stop starting new units at 5 in progress; a workspace wanting
  the old behaviour sets the key high.

- A unit whose groups already landed in its predecessor and whose tier 1 passes
  on the whole repo ends `satisfied` instead of failing: its PR is closed with
  the reason, its groups are ticked and its dependents look through it. A
  change archives once its satisfied units' work has merged. **Breaking for
  third-party integrations:** `Forge` gains `close_pr` and `permitted_commands`,
  and toolchain profiles gain `lint_command_all_files()` and
  `test_commands_all(repo, root_extras)`.

- `limits.stack_depth_cap` is renamed `limits.stack_depth_build_cap`. An
  `abk.yaml` still using the old name fails to load, naming the new one, so
  existing installations must rename it. New `limits.stack_depth_rebase_cap`
  (default: the build cap) bounds how deep a merge restacks a dependent: one
  left beyond it is held with a note naming the depth and cap, its PR is
  retargeted and its parent's branch kept, and a later merge in the same repo
  restacks it once its depth is within the cap.

- The usage threshold ramps instead of being flat: each window (five-hour
  session, seven-day week) may be run from `limits.usage_pause_pct` up to
  `limits.usage_ceiling_pct` (90) over the last `limits.usage_relief_fraction`
  of *that* window, measured against its own reset. Quota unused at a reset is
  lost, and the ceiling stays below the point where credits pay. A pause now
  resumes when the ramp would offer `limits.usage_resume_buffer_pct` of room
  above current usage, capped at six hours so a weekly window resetting days
  out re-reads rather than sleeping through it. `abk status` prints each
  window as `used%/threshold%` with its time to reset.
- A workspace names its agent runtime in `abk.yaml` (`runtime:`, default
  `claude_code`), with an optional `runtimes.<name>` entry for its command,
  its policy fix and its own model names; `ABK_RUNTIME` overrides it on one
  machine. An unknown runtime or a missing required fact fails at load.
  `abk doctor` reports the runtime, its policy coverage, and any forbidden
  command class it does not refuse; `abk init` offers to run the
  installation's fix, only once asked. Its answer is kept for a few minutes
  in `runs/policy-check.json`: an existing installation adds that path to its
  `.gitignore` (new ones get it from `abk init`).
- `tracks.model` still defaults to Claude Code's `sonnet` and is not resolved
  per runtime: a workspace selecting another runtime sets it.
- `abk tick` keeps its build slots full: every finished build is followed by
  a fetch, a poll and a fresh readiness check, and the pass goes on until
  nothing is ready or in flight. A pass can now run for hours; a timer's next
  tick waits for it. Poll events for a unit whose build is running are left
  for a later poll instead of being acted on mid-build, and a unit whose
  parent merged while it built stops before pushing and is restacked when it
  resumes.
- The review loop can converge instead of only approving or asking again.
  Every round is told which round it is, how many remain, and what running
  out costs. A verdict may approve while deferring an optional follow-up,
  recorded against the change for its next unit and the PR to see —
  correctness, a test that would pass regardless, a missing test a task
  asked for, and anything the command policy forbids stay non-deferrable. A
  reviewer that meets another instance of a kind it cannot enumerate, or that
  still disagrees after the builder declined a point once, escalates instead
  of spending another round, holding the unit for a person with its reasoning
  recorded. When the round budget is spent with blocking work still
  outstanding, the branch is pushed and its PR carries the open points
  instead of the work being discarded.

## 0.1.0 — 2026-09-28

First release, extracted from a private planning repo where the pipeline had
been running against a two-repo workspace.

- `abk` CLI: `tick`, `status`, `graph`, `verify`, `tags`, `check`, `archive`,
  `openspec`, `gate`, `init`, `install-skills`, `doctor`, `config`,
  `scrub-check`, `track`.
- Every installation fact — repos, owners, deploy rules, relationships,
  limits, models — comes from the planning repo's `abk.yaml`; nothing is
  derived from where the framework's source sits.
- Toolchain profiles: `python-uv` implemented; `node-npm` declared.
- Deploy conventions: test and documentation paths deploy nothing; a change
  in a workspace library redeploys the members that declare it as a
  dependency.
- The OpenSpec CLI runs through `npx`, pinned by `settings.openspec_version`.
- The policy hook is registered as `<interpreter> -m agent_build_kit.hooks.policy --specs <dir>`.
- One tier-2 lock, in the state directory, shared by tier 2 and the
  post-merge verify (they used to lock different files).
