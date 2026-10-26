# Proposal

## Why

The model behind an ACP agent is billed by its provider against a monthly budget. When the budget is spent, every tier 2 test that drives that
agent fails or hangs, and nothing in the pipeline knows why: the failure is recorded as pre-existing and parks units behind a fix nobody can make.
`tier2-tests-are-tagged-by-runtime` gives a repo tier 2 splits that can be held so their tests park while the rest run, but a person has to hold a split by hand and
remember to release it. The pipeline already knows how to spend a usage window gradually (stop starting work at a percentage, release more of the
window as its reset approaches, resume when there is room); that knowledge is today reachable only for the Claude Code account, because the
settings are refused on every other runtime. A provider's billing month is the same kind of window, so the same rule should govern it, and the
hold should follow the reading by itself. It belongs to the split whose tests need the metered model, not to a runtime: a split can be held for any reason, and a gate is how a
reason is checked.

## What Changes

- **A split's gate names the model provider.** `tests.tier2_splits.<name>.gate.provider` takes `name` (a row of a small provider table in the kit, first row `modal`),
  `budget_usd` (the usage cap before credits; the provider's tools do not expose it, so it is configured) and `limits`. No runtime carries a provider.
- **The kit reads usage through the provider's library, an optional extra.** For `modal` it reads the workspace's billing summary, takes
  `metered_cost` and compares it with `budget_usd`; the window is the summary's own `start` to `end`. The library is the kit's new extra `modal`, which
  includes the `acp` extra (there is no use for one without the other), is imported only when a reading is taken, and must be installed in the
  installation's own environment; `abk doctor` says how.
- **The window limits apply per gated split.** `gate.provider.limits` takes the same four limits and defaults, and the same threshold, ramp and resume buffer code that Claude's windows use
  decides it. Every split with a gate is evaluated, whichever runtime builds.
- **The result is the held-split state.** Over the threshold the split is written into the held set of `tier2-splits-replace-runtime-tags` with
  `source: gate`, an `until` at the end of the window, and the numbers in the reason; it lifts when usage falls below the resume line or the month
  turns. A hold set by hand or by the configuration is never lifted by a reading.
- **Unknown is unknown.** An unreadable or unrecognised reading is shown as unknown, never as a pass and not as a hold, unless `on_unknown: hold` is
  configured (default `allow`).
- **A generic escape hatch.** `gate.command` (an argv) answers for a provider the table does not know: exit 0 usable,
  non-zero held with the first stdout line as the reason, a timeout or an unrunnable command unknown. The documents carry a generic example script.
- **Cached and shown.** A reading is kept for `usage_cache_minutes`; `abk status` and `abk doctor` show provider, used percent and budget, when the
  window resets, the threshold now and where the figure came from.

## Impact

- agent-build-kit: `config.py` (the split declaration gains `gate`; a provider-limits model; `runtimes.<name>.limits` is untouched), a new `runtimes/providers.py` (the table, the reader, the command runner),
  `pipeline/usage_guard.py` (the window model and the ramp helpers take a provider's window), a new module that evaluates and writes the held set, `cli/pipeline.py` (the
  tick step and the `abk status` lines), `cli/doctor.py`, `docs/configuration.md`, `docs/agent-runtimes.md`, `docs/cli.md`, the `abk-config` and
  `abk-pipeline` skills, the changelog.
- Builds on `tier2-splits-replace-runtime-tags` group 1 (the split declaration) and group 4 (the held set and its writer), and on group 6 of `tier2-tests-are-tagged-by-runtime` (the
  `abk tier2` commands and the shared status lines); groups 2 and 3 stand alone and can be built before them.
- Does not change what pauses the pipeline: `supports_usage_tracking` stays false for a bring-your-own-model runtime, so units still start under it;
  only the gated split's tier 2 tests park.
- Priority 2.
