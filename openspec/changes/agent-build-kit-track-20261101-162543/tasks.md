# Tasks

Acceptance: none — documentation-only change; the unit tests read the documents.

## 1. [agent-build-kit] [unit-test] The AGENTS.md layout names every source package

Done when a test lists the package directories under `src/agent_build_kit/` and finds each one in the layout block.

- [ ] 1.1 Test: in `tests/docs/test_agents_md_layout_complete.py`, read the layout code block of `AGENTS.md` and assert every directory with an `__init__.py` under `src/agent_build_kit/` appears in it as `<name>/`, and that `docs/designs/` appears; it fails today for `trackers`, `forges`, `runtimes`, `sandboxes`, `graph`, `serve`, `notify`, `replay`, `split` and `telemetry`.
- [ ] 1.2 Add one line per missing package to the layout block in `AGENTS.md`, each written from that package's module docstrings, and `docs/designs/` to the `docs/` line.

## 2. [agent-build-kit] [unit-test] The architecture document describes the work tracker

Done when `docs/architecture.md` has a work-tracker section and `docs/hand-off.md` no longer says "interim".

- [ ] 2.1 Test: in `tests/docs/test_work_tracker_documented.py`, assert `docs/architecture.md` has a heading containing "tracker" whose section names `reconciler`, `wanted board`, `Epic` and `manual parent`, and that `docs/hand-off.md` does not contain "interim".
- [ ] 2.2 Write the "Work tracker" section in `docs/architecture.md` from `src/agent_build_kit/trackers/` (`reconciler.py`, `wanted_board.py`, `levels.py`, `manual_parent.py`, `start_decision.py`) and `pipeline/tracker_file.py`, add the tracker commands to `docs/cli.md`, reword the first paragraph of `docs/hand-off.md`, and add one `CHANGELOG.md` bullet under Unreleased.
