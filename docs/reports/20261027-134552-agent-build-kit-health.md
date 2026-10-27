# Health 20261027-134552 — agent-build-kit

**Status:** PENDING RESOLUTION — only the already-tracked `grafana-url-env-test` issue remains; nothing new

## Findings

### logs-and-errors
- No new problems in the last 24h. No unit is in `needs_person`; `install-timers-carries-the-machine-files-into-the-pipeline-worktree/1` (stuck in the previous report) is now `merged`.
- No traceback, rate-limit message or non-zero exit in the 27 Oct unit logs.
- `init-makes-the-state-home-and-the-planning-view/1` was judged `needs_person` at 03:04Z but was re-judged `none` at 13:46Z, so it is moving again.
- `test_without_a_url_it_names_the_setting_and_fails` (host `ABK_GRAFANA_URL`) — already in flight as `grafana-url-env-test` (change `agent-build-kit-track-20261026-125001`).
- Flaky tests: `state/flakes.jsonl` has 11 entries; the recent ones already have `fix-flaky-tests-*` changes.

### resource-usage
- Disk 84% used (157G free), 20G memory available, swap unused, `runs/` 5.6M. Nothing wrong.

### llm-observability
- Nothing applies: no LLM call sites of its own, and OpenTelemetry export is opt-in and unconfigured.

### pipeline-health
- 593 units: 487 merged, 83 unplanned (backlog), 8 satisfied, 6 planned, 3 running, 3 closed, 3 retired. None failed, held or in review.
- Three units showed as `running` with no log writes since about 21:00–21:40 local, and ticks recorded no decisions overnight. This was most likely throttling from the model budget (seen the previous day). At 13:46Z a tick ran, new `claude -p` agents were running and a fresh decision was logged, so the pipeline has resumed. Not a fault now.
- Tick cadence is normal (tick 112 at 13:44Z).

### secrets-scan
- No secrets found in the last 24h of committed changes. The only hits were change names matching the `sk-` pattern. No tracked `.env`, key or `abk.local.yaml` files. Untracked working-tree files were not scanned.

## Actionable candidates for the next propose run

None this run
