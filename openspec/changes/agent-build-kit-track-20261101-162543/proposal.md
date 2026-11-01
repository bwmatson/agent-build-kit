## Why

The 20261101-162543 improve run (readme-drift section) found two places where the documents have
fallen behind the code:

- The layout block of `AGENTS.md` lists a subset of the packages under `src/agent_build_kit/`.
  `trackers/`, `forges/`, `runtimes/`, `sandboxes/`, `graph/`, `serve/`, `notify/`, `replay/`,
  `split/` and `telemetry/` are missing, and so is `docs/designs/`. An agent that navigates by
  that block does not find them.
- The work-tracker subsystem (`src/agent_build_kit/trackers/`) has no section in
  `docs/architecture.md` and nothing in `docs/cli.md`, and `docs/hand-off.md` still calls the
  tracker hold "interim".

Each is a documentation fix with one reasonable shape, and each gets a test so it does not drift
again.

## What Changes

- A test fails when a package under `src/agent_build_kit/` is absent from the `AGENTS.md` layout
  block; the block is completed.
- A test fails when `docs/architecture.md` has no work-tracker section or `docs/hand-off.md`
  still says "interim"; the section is written from the code and the wording fixed.

## Capabilities

### New Capabilities
- `layout-docs-cover-every-package`: the `AGENTS.md` layout names every source package.
- `tracker-docs`: the work tracker is described in the architecture document.

## Impact

`AGENTS.md`, `docs/architecture.md`, `docs/cli.md`, `docs/hand-off.md`, `CHANGELOG.md` and two
new tests under `tests/docs/`. No production code.
