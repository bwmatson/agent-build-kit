# Changelog

## Unreleased

- A unit whose groups already landed in its predecessor and whose tier 1 passes
  on the whole repo ends `satisfied` instead of failing: its PR is closed with
  the reason, its groups are ticked and its dependents look through it. A
  change archives once its satisfied units' work has merged. **Breaking for
  third-party integrations:** `Forge` gains `close_pr` and `permitted_commands`,
  and toolchain profiles gain `lint_command_all_files()` and
  `test_commands_all(repo, root_extras)`.

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
