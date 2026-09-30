# Changelog

## Unreleased

- A unit fetches its repo before it restacks and again before it pushes, asks
  the forge whether its parent merged (recording a merge the store missed) and
  moves onto the base as it now is. The move before a push never runs the
  conflict resolver: a conflict, or a tier 1 or tier 2 failure on the moved
  commit, holds the unit to resume at its restack, where resolution runs under
  the usage gate and review is told of it. A pull request refused for a missing
  base holds the unit instead of failing it; each forge recognises its own
  error for that.

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

- New `limits.max_open_prs` (default 5, at least 1) caps open pull requests
  across all repos. At the ceiling no new unit starts: it stays `planned`, and
  the tick log and `abk status` say "queue is full: N open pull requests,
  ceiling M". Reworks, restacks, further review rounds and PR opening
  continue, so the count can go past the ceiling. Free slots now go to units
  with an open PR first, then resuming builds, then new units. **Behaviour
  change:** installations that were unbounded now stop starting new units at 5
  open PRs; a workspace wanting the old behaviour sets the key high.

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
