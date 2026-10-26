# Follow-ups

## DONE: remove the temporary backfill command (written as `remove-cost-backfill-command`)

TODO: remove `abk usage backfill-costs`, its tests and docs, once it has been run with `--apply` on every installation
that has a ledger and `abk usage backfill-costs` reports no legacy rows; the legacy-row reader tolerance stays.

This is deliberately not a task group. A group would be planned and built at once, before anyone has run the command.
Removal is a small change of its own, written when the runs are done.
## From `usage-cost-and-context-are-recorded/1`

- The ACP fallback in `_cost` (graph/nodes.py:746) is tested only through the `Cumulative` stand-in. That stand-in now returns `cost_usd` and `cumulative_cost_usd` the way `runtimes/acp.py` `_spent` does. A graph-level test that drives the real `AcpRuntime` over `tests/runtimes/acp_agent.py` (`resume=True, prior_cost=0.5, cost="USD"`) would catch any later change to how `_spent` fills these fields.

## From `usage-cost-and-context-are-recorded/2`

- Backfill: summaries the predecessor's archive wrote (no `cost_basis`, sometimes a `legacy` block) are marked `cumulative_summed` and listed as not corrected even though they were summed from increments. Skip at least those that carry `legacy`, and fix the docs/cli.md sentence about archive-written summaries.
- `roll_up_change` writes `cost_basis: reported` on summaries, but in the design's table `reported` means a per-call runtime figure. Pick a value that means 'summed from incremental figures' and document the summary's `cost_basis` in docs/architecture.md.
- `_when` in cli/usage_cmd.py: a detail row with an unparseable `at` counts as covered by any summary, so `--apply` drops that summary. Treat such a row as not covered and fix the docstring.
- In tests/cli/test_usage_backfill_costs.py, take the worked session's totals from `ledger_lines.WORKED_SESSION` instead of retyping them.
- src/agent_build_kit/cli/usage_cmd.py:192 — Some summaries lack a `cost_basis` and survive without detail, yet were summed from incremental figures: the archive running the predecessor's code wrote them (on main since unit 1 merged). The backfill marks them `cumulative_summed` and lists them as 'not corrected'. A summary that carries a `legacy` block can only have come from that code.
- src/agent_build_kit/pipeline/usage_report.py:726 — Summaries the archive writes now record `cost_basis: "reported"`. The design defines `reported` as 'the runtime gave the call's own figure'. A sum of increments, including backfilled or derived ones, is not that. The value is written into ledgers for good, and docs/architecture.md does not describe a summary's `cost_basis`.
- src/agent_build_kit/cli/usage_cmd.py:70 — The `_when` docstring says an unparseable timestamp 'never covers a later row'. That holds for a summary's `at`. A detail row with a bad `at` does the reverse: it sorts to datetime.min, so any summary counts as built from it. The summary is then dropped and rebuilt from that row alone.
- tests/cli/test_usage_backfill_costs.py:307 — The worked session's running totals are retyped here. `tests/ledger_lines.WORKED_SESSION` already holds them.
- src/agent_build_kit/cli/usage_cmd.py:241 — `_write` repeats the scratch-file and `os.replace` rewrite that `roll_up_change` already does inline.
## From `usage-cost-and-context-are-recorded/3`

- `request_fills` takes the model from the first non-sub-agent assistant event (`model = model or message.get("model")`). If a run switches model partway, for example after a fallback, the window is looked up under the first model, not the last. The last main-conversation model would be the better key for `used_end` and the near-limit warning. Today nothing is wrong, because the lookup falls back to `request.model` and then to the table.
