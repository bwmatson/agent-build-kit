# Changelog

## Unreleased

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

- New runtime dependencies: `langgraph`, `langgraph-checkpoint`,
  `langgraph-checkpoint-sqlite` and `aiosqlite`, for the unit graph engine. A new setting,
  `ABK_ENGINE` (`classic` by default, or `graph`), picks the engine that builds a unit. `graph`
  is not usable yet: the build path (prepare through opening the pull request) is built and
  tested behind it, but the engine is not yet driven by a tick, so nothing changes for an
  installation that does not opt in. An unknown value is now refused when settings load, so a
  mistyped `ABK_ENGINE` stops every command rather than falling back to `classic`.

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
