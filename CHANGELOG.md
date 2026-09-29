# Changelog

## Unreleased

- The usage threshold ramps instead of being flat: each window (five-hour
  session, seven-day week) may be run from `limits.usage_pause_pct` up to
  `limits.usage_ceiling_pct` (90) over the last `limits.usage_relief_fraction`
  of *that* window, measured against its own reset. Quota unused at a reset is
  lost, and the ceiling stays below the point where credits pay. A pause now
  resumes when the ramp would offer `limits.usage_resume_buffer_pct` of room
  above current usage, capped at six hours so a weekly window resetting days
  out re-reads rather than sleeping through it. `abk status` prints each
  window as `used%/threshold%` with its time to reset.

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
