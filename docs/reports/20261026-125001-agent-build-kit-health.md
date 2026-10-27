# Health 20261026-125001 — agent-build-kit

**Status:** ATTENTION — unit install-timers-carries-the-machine-files-into-the-pipeline-worktree/1 is stuck in needs_person on 7 unit-test failures that also fail on the base commit

## Findings

### logs-and-errors
- Unit `install-timers-carries-the-machine-files-into-the-pipeline-worktree/1` failed ("checks failing and fix round 1 changed nothing, before review"; `runs/unit-logs/install-timers-carries-the-machine-files-into-the-pipeline-worktree-01-20261026-033625-implement.log:348-352`), recorded `needs_person` at 04:10Z in `runs/decisions.jsonl`. Unit `/2` is blocked behind it.
- Cause: 7 unit-test failures (14,658 pass) that the agent reproduced on base commit `f889d553`, so the unit did not cause them:
  - `tests/test_no_installation_leaks.py`: `test_no_home_paths_in_text`, `test_no_issue_or_pr_number_anecdotes`, `test_no_dated_anecdotes` (flag planning content under `openspec/` and `runs/`).
  - `tests/docs/test_review_docs_status.py::test_no_document_names_a_removed_key_outside_the_migration`.
  - `tests/docs/test_no_human_merges_every_pr.py::test_no_markdown_file_states_a_person_merges_every_pull_request`.
  - `tests/test_live_test_names.py::test_no_tracked_file_names_an_old_module` (flags `openspec/changes/…`).
  - `tests/cli/test_telemetry_push_dashboard.py::test_without_a_url_it_names_the_setting_and_fails` (fails because the host environment sets `ABK_GRAFANA_URL`; test is not environment-independent).
- Until fixed, every unit's unit-test check fails the same way.
- Three units (`ui-chat-editing/6`, `dry-guidance/5`, `abk-web-ui/12`) were waiting on "the model backend's budget is spent" at 03:11Z — likely expected throttling.

### resource-usage
- Root filesystem 88% used (119G free of 1007G) — not urgent. `runs/` is 4.2M. Load, memory, OOM and container checks were not done (a command was denied). No containers expected for this project.

### llm-observability
- Nothing applies: OpenTelemetry settings are all commented out in `.env.example`; no trace backend configured.

### pipeline-health
- Ticks run about every 6 minutes (tick 92 at 12:47Z, idle outcomes); environment check healthy. 582 units: 481 merged, 83 unplanned, 8 satisfied, 5 planned, 3 closed, 1 retired, 1 failed (which one was not identified).
- The `needs_person` unit above is the stall; nothing has moved since 04:10Z.
- Usage forecast uncalibrated (`too_few_pairs` for session and weekly windows) — informational.

### secrets-scan
- No committed secrets found. Pattern search covered the working tree (git/gitleaks were unavailable). Only hits are redaction pattern literals/fixtures (`src/agent_build_kit/redaction.py:30`, `tests/test_redaction.py:66`, `docs/architecture.md:1600`).

## Actionable candidates for the next propose run

1. [proposed — agent-build-kit-track-20261026-125001] (partly: only the ABK_GRAFANA_URL test; the six guard failures were left for a person) Make the suite green on the base commit so units can pass their unit-test check: the 7 failures listed under logs-and-errors (scrub dates/home paths/PR-number anecdotes and removed-key, old merge-rule and old-module-name mentions from `openspec/` and `runs/` content or exempt that content in the guards, and make `test_without_a_url_it_names_the_setting_and_fails` clear `ABK_GRAFANA_URL` from its environment). This unblocks `install-timers-carries-the-machine-files-into-the-pipeline-worktree/1` and `/2`.
