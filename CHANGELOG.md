# Changelog

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
