## From `abk-web-ui/1`

- cmd_serve drives RunningServer's __enter__/__exit__ by hand. Replace this with ExitStack or a named start() method.
- The port-in-use test leaves a PytestUnhandledThreadExceptionWarning from uvicorn's SystemExit(3) in the server thread. Filter it in the test or catch it in the thread target.
- src/agent_build_kit/cli/serve_cmd.py:15 — cmd_serve calls `running.__enter__()` and `running.__exit__(None, None, None)` by hand to tell a failed start apart from the serve loop. That is harder to read than the `with` block it replaced.
- tests/serve/test_serve_binding.py:53 — The port-in-use test leaves a PytestUnhandledThreadExceptionWarning. Uvicorn's server thread ends with `SystemExit(3)` when the bind fails, and the test does not expect it.
## From `abk-web-ui/3`

- serve/server.py run_lines: a `continues` entry carries `at` = the run's start time, because `clock` restarts from `started` on each poll. Either set it to None or document that `at` is meaningless when `continues` is true, before the web UI unit uses it.
- cli/pipeline.py _build_unit: nothing tests the `journal=journal_only, transcript=unit_log_only` wiring. Add an end-to-end run-log/journal check if `_build_unit` gets a seam.
- src/agent_build_kit/serve/server.py:238 — The `continues` entry that opens a later poll gets the run's start time as its `at`, because `clock` is reset to `started` on every poll. It does not get the time of the entry it continues.
- src/agent_build_kit/cli/pipeline.py:1696 — Nothing tests that `journal_only` and `unit_log_only` are the closures `_build_unit` passes as `journal` and `transcript`. The builder left out the end-to-end check because `_build_unit` has no seam short of running the whole unit thread. The earlier round asked for that check only if such a seam existed.

## From `abk-web-ui/4`

- Compute `failed_check` once per unit-test failure and give the same value to both the exported counter and the local record, so the two cannot disagree when classification raises (nodes.py record_check_failure and its two callers).
- Each metric emit site has a `telemetry.*` call and a `record_metric` call side by side. Consider one helper that does both, so a future site or attribute change cannot update only one of them.
- Add a test for the round-0 check failure that the `unit-test` node itself records (nodes.py ~1044).
- Group 5's catalogue will list every instrument, but `abk.units.reclaimed`, `abk.leftovers.resumed` and `abk.step.duration` have no local records yet. Group 5 should either derive them from files it already has or add records for them, so that 'every exported metric can be rebuilt' holds.
- Metric lines are never rolled up, so the ledger grows by one tick record per tick indefinitely, and every report or serve read loads the whole file. Consider rotation or compaction once the metrics page reads these records.
- src/agent_build_kit/graph/nodes.py:494 — Each unit-test failure site now runs `failed_check` twice: once inside the lazy `telemetry.count` attribute and once in `record_check_failure`. The two can also disagree. If `failed_check` raises, telemetry's `_safely` drops the exported count, but the record is still written with check="unknown". That breaks docs/architecture.md's claim that 'a total derived from the records equals the exported one' for this path.
- src/agent_build_kit/cli/pipeline.py:1658 — Each of the seven emit sites now has two parallel calls with the same name, value and attributes: one to `telemetry.X` and one to `record_metric`. A later edit to one call can easily miss the other.
- tests/cli/test_metric_records_tick.py:95 — Only the rework-path unit-test failure (nodes.py:775) is exercised. The `unit-test` node's own failure site (nodes.py:1044, round=0) has no test that it appends a record.

## From `abk-web-ui/2`

- The pipeline's own gate for this repo never runs the web checks. The python-uv profile (profiles/python_uv.py:165-178) runs `uv run pre-commit run` and pytest, not `poe format`, so `web-check` (prettier, eslint, tsc, vitest) is not part of what a unit's build is judged on. Later units of this change that touch web/ (groups 5, 8 and 9) can break its types or tests and still pass the pipeline. Fixing it means deciding how build worktrees get node_modules: a pre-commit hook scoped to ^web/ that runs `npm ci` when node_modules is missing, or a tier-1 command from the profile. Decide that before those units build.
- In server.py, the 503 text says to run `npm install && npm run build` in web/. For someone running an installed wheel, there is no web/. The message could also mention `uv run poe web-build` from a checkout, or say the wheel was built without the UI.

## From `abk-web-ui/5`

- src/agent_build_kit/serve/metrics.py `_metric_records_in` copies the loop in `pipeline.metric_records.read_metrics`. Add a public `metrics_in(lines)` to metric_records.py, make `read_metrics` call it, and have LocalSource call it too, so there is one parser for `metric` lines.
- tests/serve/test_serve_metrics.py `test_with_prometheus_down_the_ledgers_metric_records_draw_their_charts` writes the `metric` lines by hand without `unit`/`change`. The test could build them with `MetricRecord(...).model_dump()` instead, so the fixture always matches what `record_metric` actually writes.
- src/agent_build_kit/serve/metrics.py:306 — `_metric_records_in(lines)` repeats the loop body of `pipeline.metric_records.read_metrics` line for line: the same `kind == "metric"` filter, the same `model_validate` call and the same exceptions skipped. There are now two parsers of the same ledger record in two modules.

## From `abk-web-ui/6`

- For a person: the session-reuse change's group 5 spec (resume only via `session/resume` after `session/list`, never `session/load`) still contradicts this unit's agent-runtime spec (load via `session/load` where `loadSession` is declared). Reconcile the two in the planning repo before session-reuse group 5 is planned, or that group will undo this unit's load path.
- A resume that cannot load now starts and initializes the agent process twice: once for the refused resume, once for the node's fresh run. That is fine for correctness. If startup cost matters later, the runtime could check the `loadSession` capability before the resume attempt.

## From `abk-web-ui/7`

- Retention by run is tested only at the `Transcript` level (`test_a_runs_calls_are_one_run_to_retention_and_go_together`), which supplies the shared stamp itself. `build_runner` creating one `datetime.now(UTC)` and passing it to `build_run`, `run_review` and `run_rework_review` (src/agent_build_kit/pipeline/wiring.py:1848) has no test. Suppose a later edit moved the stamp back into `_recorder`. Every existing test would still pass, and the transcripts would again be pruned per call. A wiring-level test would catch that: drive two calls of one runner with `runs_kept=1` and assert both files survive.
- The port commit's subject, 'The session bridge, chat and sessions page', is group 8's title, but this unit implements group 7 (agent transcripts). If the PR title is taken from that subject, correct it when the PR is opened.

## From `abk-web-ui/8`

- web/src/agui.ts: the new `continued_as_new` branch of `reduce`, and the status line it drives in web/src/sessions.tsx, have no vitest. Add a reducer test: a CUSTOM `continued_as_new` event sets `continuedAsNew` to true. Add a render test: Reply shows the status line when it is set.
- serve/chat.py `resumable`: when the answer is no, it is not cached, so every GET /api/sessions/acp/<id> for a session the agent cannot resume starts the agent process again to ask. Consider caching a negative answer for a short time if the sessions page polls.

## From `abk-web-ui/9`

- Unit page: move the action buttons above the tab bar to match docs/cli.md ('Above the tabs'), or correct the doc.
- Unit page: offer requeue's rework and restart modes, which the endpoint already accepts as `mode`.
- test_chat_guards.py and test_chat_attachments.py: use per-run uuid session ids as test_chat_sessions.py now does, instead of fixed ids differing by one digit.
- test_an_action_waits_for_the_stores_lock: assert the lock was taken and wait for the deferred requeue to land before the test ends.
- web/src/pages.tsx:171 — `<Actions>` renders after the tab bar, and on the Status tab it also comes after the status content. docs/cli.md says the action buttons sit 'Above the tabs'.
- web/src/pages.tsx:85 — The page can only requeue in resume mode. `postAction` always sends `{}`, so rework and restart can only be reached through the API's `mode` body, not from the unit's page.
- tests/serve/test_chat_guards.py:49 — The check rounds made the session ids fresh per run with uuid in test_chat_sessions.py and acp_agent.py, but only changed one digit of the fixed ids in test_chat_guards.py and test_chat_attachments.py.
- tests/serve/test_serve_actions.py:84 — `test_an_action_waits_for_the_stores_lock` never checks `held.wait(5)`. The request it lets time out also keeps running in the server thread and writes to the store once the lock is released, after the assertions.

## From `abk-web-ui/10`

- `review_round` now has a public name, but it still lives in serve/server.py, and the CLI has to import it inside the function because the top-level import would be circular. Moving it next to `branch_tip` in serve/review.py, or into a pipeline-level module, would remove that import cycle. `server.py:318` also still reads `run.review_round` inline instead of calling the helper.
- In docs/cli.md the last line of the rewrapped Approve paragraph ("that already has a decision. Each refusal carries the CLI's reason, and the unit page shows the buttons disabled with it.") still runs past the paragraph's wrap width. The architecture.md line that was changed is also long.
## From `abk-web-ui/11`

- The in-process server in the serve test builds its Installation from the test process's own settings, and the ABK_WORKTREE_ROOT environment variable takes precedence over planning.worktree_root (installation.py:71). If a developer's shell exports ABK_WORKTREE_ROOT, the server and the ticks would resolve different worktree roots. Setting it to the same path in the test's environment, or clearing it there, would remove that dependence on the machine.
