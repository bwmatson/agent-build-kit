# Design (a split's gate)

## What was checked, and where

Read-only against agent-build-kit `origin/main` (`54ad609f`); paths are under `src/agent_build_kit/`.

- `config.py`: `RuntimeConfig` (352) holds `command`, `policy_fix`, `policy`, `policy_extra`, `models`, `context_windows` and `limits: ClaudeLimitsConfig`.
  `Frozen` forbids unknown keys, so every new key needs a field. `UsageWindowConfig` (180) is one window's settings (`usage_pause_pct`,
  `usage_pause_ceiling_pct` with the `usage_ceiling_pct` property, `usage_relief_fraction`, `usage_resume_buffer_pct`, `usage_unit_allowance_pct`,
  `usage_allowance_floor_pct`, and a validator that the ceiling is not below the pause percent). `ClaudeLimitsConfig` (243) is two of them (`session`,
  `weekly`) plus the reading cache and estimate settings. `WorkspaceConfig._usage_limits_only_on_claude` (942) refuses `runtimes.<name>.limits` on any
  runtime but `claude_code` (the `CLAUDE_CODE` constant). `load` then runs `_check_runtime`, which fails an unknown selected runtime; there is no
  per-entry check of the other `runtimes.<name>` keys.
- `pipeline/usage_guard.py`: `Window` (134) is `name: Literal["session","weekly"]`, `used_pct`, `resets_at`, `length`. `Band` and `Limits` (344 to 378)
  are the ramp's numbers, built from config by `Limits.configured()` through `claude_limits()` (472). `threshold_at` (387) is the pause percent until the
  last `usage_relief_fraction` of the window, then a straight line to the ceiling at the reset; `relief_at` (410) is when `used + usage_resume_buffer_pct`
  first fits under the threshold. `_threshold_note`, `_resume_to` and `_hhmm` (1326 to 1361) word and bound the result. `may_start_unit` (922) is Claude's
  decision: a refusal when `used >= threshold`, plus credit backstops, staleness and per-start allowances and estimates that exist only because a unit
  spends a share of a subscription window. `decide_start` (1229) wraps it in the reading cache (`usage-cache.json` and the calls record in the state
  directory, `usage_cache_minutes`, doubling on refusals).
- `runtimes/base.py`: `supports_usage_tracking` (276) and `get_usage_status` (310) describe the build account's window; `UsageStatus` (259) is
  session and weekly percentages. `runtimes/acp.py` (1231, 1635) sets the flag false and `get_usage_status` returns None. The start decision
  (`cli/pipeline.py` about 1268) and `abk status` (481 to 553) consult the flag, so a runtime without it is never held by a usage window.
- `runtimes/known_agents.py` is the pattern: data and a probe, `Run` and `Which` injected (`runtimes/base.py` 320), the module the only place product
  names appear. `pipeline/shell.py` runs `gh auth token --user <owner>` with `subprocess.run(..., capture_output=True, text=True, check=False)`, the
  precedent for calling an installed tool and treating a missing one as no answer. `redaction.py` has `redact_text`.
- `cli/doctor.py` `_runtime` (936) checks only the active runtime; `run_doctor` (1133) assembles the checks. `cli/pipeline.py` `cmd_status` prints the
  usage lines for the active runtime only.

## What was confirmed about the provider

Read-only, with the installed library (version 1.5.3) and one call of the workspace's billing summary; nothing was changed at the provider.

- `Workspace.from_context().billing.summary()` returns an object with `start` and `end` (UTC datetimes, currently 2026-10-01 00:00 to 2026-11-01
  00:00), `metered_cost` (a decimal), `metered_cost_breakdown`, `adjustments` and `billed_cost`. `from_context()` uses the active profile of the
  library's configuration file, or the token id and secret environment variables. So the window is read from the summary, not guessed: this resolves
  the earlier question of when the billing month turns, and the calendar-month computation survives only as the fallback for a summary that lacks
  `start` or `end`.
- **Why the library and not the command.** The command-line tool's JSON for the same summary prints only `metered_cost`, `billed_cost`, `adjustments`
  and `metered_cost_breakdown`: it drops `start` and `end`, which are what the ramp needs for its reset. The library is the only route to them, so
  the command path (and the setting that replaced its argv) is not kept: two readers of one number would need a rule for which wins.
- The budget (a usage cap before credits) is not readable by the library or the command: `Workspace` offers `billing`, `settings`, `members` and
  `proxy_tokens`, `billing` offers `report` and `summary`, and the workspace settings list shows only a default environment and an image-builder
  version. So `budget_usd` is configuration, and used percent is `metered_cost / budget_usd`. `billed_cost` and `adjustments` are not used: credits
  lower what is charged but not what counts against a usage cap before credits.
- `billing.report(start, end, resolution="d"|"h", tag_names)` exists (hourly reports cannot span more than seven days) and gives one row per object per
  interval.
- The library requires Python 3.10 to 3.14 and pulls in an HTTP client, a protocol stack (`grpclib`, `protobuf`), `click`, `rich`, `toml`,
  `watchfiles`, `cbor2` and `synchronicity`; the documents list what the extra adds, since the installation's environment gets it all.

## Decisions

This change is "a split's gate". The directory keeps its name because renaming it would orphan the stored units; the text says splits. A tier 2 split is a named subset of a repo's tier 2
tests (`tier2-splits-replace-runtime-tags`), a split is held by `hold`, by `abk tier2 hold` or by its **gate**, and a gate is either a provider's usage window or a command. Nothing in the
mechanism names a runtime: what was `runtimes.<name>.<redacted>_provider` and `availability_command` is `tests.tier2_splits.<name>.gate.provider` and `gate.command`, and a runtime's `limits`
stay Claude Code's alone.

```yaml
tests:
  tier2_splits:
    acp:
      marker: runtime_acp
      gate:
        provider:
          name: modal
          budget_usd: 200
          limits: {usage_pause_pct: 70, usage_pause_ceiling_pct: 90}
        on_unknown: allow
```

**One provider setting, one small table.** `gate.provider` (`name`, `budget_usd`, `limits`) names a row of a table in `runtimes/providers.py`, beside `known_agents.py`
and under the same rule: product names appear in that module and in the documents' section about it, nowhere else in framework text (a test of `tier2-splits-replace-runtime-tags` group 10
exempts that module and no other). A row says: how to read usage, the settings it requires (`budget_usd` for `modal`), how to turn the result into a reading (used amount, window
start, window end, or unknown), and what to tell a person who cannot get a reading. Adding a provider is adding a row and a reader.

**The library is an optional extra, imported lazily, behind one function.** `pyproject.toml` gains the extra `modal = ["agent-build-kit[acp]", "modal>=1.5,<2"]`, declared beside `acp` and `telemetry`. It includes `acp` because the
provider is used with an ACP agent. The self-reference is the form the development group already writes (`agent-build-kit[acp,telemetry]`), and a
throwaway project whose extra named its own project's other extra locked in uv 0.11, so no different form is needed. The installation then needs only
`agent-build-kit[modal]` or `--extra modal`, and the doctor's hint names only `modal`. The development group's `agent-build-kit[acp,telemetry]` becomes `agent-build-kit[modal,telemetry]` (`modal` brings `acp`), so a contributor's or the
pipeline's `uv sync` has the library and tier 1 can import its summary type and build it by hand for the parser's tests; no tier 1 test calls the
provider or needs an account. The lock changes with `pyproject.toml` and must be regenerated (`uv lock`) in the unit that edits it, so CI's `uv lock
--check` passes; the kit's `generated_files` already leaves lock files out of a unit's size. The `modal` row's reading is a function of one argument
(nothing) that imports the library inside its body, builds the workspace from the active context and returns the summary; tests replace that function
with a fake that returns a hand-built summary or raises. Nothing imports the library at module import time, as `runtimes/__init__.py` imports the
`acp` runtime only inside `_load_builtin` and tolerates only the library's own absence; a test asserts every kit module imports with the library hidden
and that importing the provider module leaves it out of `sys.modules`. Because the tick runs in the installation's own virtual environment, the extra
must be present there, not in the kit's checkout: the documents give `uv sync --extra modal` in the installation and the extras form of the
installation's dependency on the kit, and the doctor prints both when the import fails, importing nothing else.

**No split is special.** Evaluation walks the declared splits (and `rest`) for every entry with a `gate`, whatever runtime the pipeline builds on, because a test in one split may run
while another runtime builds.

**The same ramp code, one window.** A provider has a single window, so `gate.provider.limits` is flat: the four window limits, with the same
names, defaults and ceiling check as `UsageWindowConfig` (the model `ProviderLimitsConfig`, not a `ClaudeLimitsConfig`, whose two sections and subscription settings would mean nothing
here); the allowance settings are refused with a message saying why (a start does not spend a known share of a monthly budget, so no allowance or estimate applies, and a reading is
judged as read). The two cache settings, `usage_cache_minutes` and `usage_stale_retry_minutes`, sit on the gate beside `on_unknown` and `timeout_seconds`, because a command gate needs them
too and has no `limits`. `Window.name` widens from the two literals to a `str` for the provider's window (`billing`); `Band`, `threshold_at`, `relief_at`, `_threshold_note`, `_resume_to`
and `_hhmm` are used unchanged on a `Band` built from the provider's limits. The provider decision is a small pure function in `usage_guard.py` beside `may_start_unit` (no credit
backstops, no staleness rule, no allowance): held when `used_pct >= threshold_at(...)`. `runtimes.<name>.limits` and `_usage_limits_only_on_claude` are not touched.

**Hysteresis from the existing resume buffer.** A hold the gate wrote stands until `used_pct + usage_resume_buffer_pct <= threshold` (the line
`relief_at` already draws for waking a paused pipeline), or until the end of the window. Without it a month's spend creeping past a threshold would
write and lift the hold on alternate reads. Not held yet, the test is the plain `used_pct >= threshold`.

**The result is the held-split file, not a new gate on the pipeline.** The evaluation writes and lifts entries in `<state_dir>/tier2-held.json`, the file group 4 of
`tier2-splits-replace-runtime-tags` defines (per split: reason, since, until, source, by). Every reader of that file (tier 2 selection, the park, `abk tier2 status`, `abk status`)
works unchanged. `source` is `gate`, the one value a gate writes (a command's result and a table reading alike; the earlier `provider` and `availability` values are gone); the evaluation
writes, replaces and removes only entries it wrote, and never touches an entry whose source is `command` (a hand-set hold) or a split with `hold: true`, which wins on a conflict. `until` is
the window end, so an evaluation that stops running still ends the hold at the month's turn; for a command, which has no window, it is the cache time from the reading.

What this change calls, and nothing else of that one: the file's model, its read, `write_hold` and `remove_hold` under the lock, and `held_splits` (group 4 there; the names are fixed by
that group's code and confirmed by task 4.1 here). The evaluation writes entries with `source` `gate`, `by` naming the evaluation, `since` the time written and `until` as said above;
reads the held-set function to know whether a split stands held by someone else and whether the configuration releases it; and never calls the text edit of the configuration or the
`abk tier2` commands. The `Needs:` lines follow: group 1 needs the split declaration it adds `gate` to (group 1 there); group 4, which writes and lifts entries, needs the held set (group 4
there); the status and doctor lines and the documents need group 6 of `tier2-tests-are-tagged-by-runtime`, whose `abk tier2 hold`, `release` and `status` commands and shared lines they extend
and point to. A gate entry is lifted only by this evaluation or by `abk tier2 release`, which tells the person the gate may hold it again.

**Unknown stays unknown.** A reading the kit cannot take (the extra is not installed, the call raises for want of a login or the network, a summary with
a missing or non-numeric `metered_cost`, a budget that is not positive) is an `unknown` result with its reason. It is shown as unknown. By
default (`on_unknown: allow`) it writes nothing and lifts nothing: a standing gate hold stays until its `until` or a good reading, and a split
with no hold stays usable. With `on_unknown: hold` it writes a gate entry saying the usage is unknown, with `until` one
`usage_stale_retry_minutes` away, renewed by each unknown evaluation and lifted by the first good reading. `on_unknown` is a gate-level setting
because it applies to both a provider and a command; allowing is the default because a library that is not installed, or a login that
lapsed, is as likely a setup gap as an exhausted budget and a hold that nobody asked for hides work.

**A reading and its life.** Per split, in `<state_dir>/gate-usage.json` (written whole through `atomic_write_text` under a file lock, so a
process outside the tick never sees half of it): the parsed reading or the unknown reason, when it was taken, and the window end it assumed. A good
reading answers every reader for `usage_cache_minutes` (default 15) and never past its window end; an unknown result is kept for
`usage_stale_retry_minutes` (default 5), so a missing tool is not spawned on every tick. `abk status --refresh` and `abk doctor` ask now.
A reading older than its life is not estimated forward; there is no climb model, because the month moves in cents and the interval is minutes. The
first call into the library can take seconds (the library connects to its service); the read runs with the evaluation's own timeout and an exception
of any kind, a timeout included, is unknown.

**Evaluation points.** Once per tick round, before the step that selects tier 2 tests and before planning, for every split with a gate
(`abk tick --dry-run` reads and reports, and writes nothing); and `abk status --refresh`. `abk status` without it shows the
reading held and calls nothing, like the existing usage line. A tier 2 step in flight is never interrupted by a hold, as no running step is judged
by the Claude threshold either.

**The gate command.** `gate.command` is an argv run without a shell, from the installation's root, with the process's
environment, with stdin closed and a timeout (`gate.timeout_seconds`, default 30). Exit 0 is usable; any other exit is held, and the reason
is the first line of stdout, trimmed, passed through the existing redaction and cut at 200 characters, or `gate command exited <n>` when
that line is empty. A command that cannot be started, or runs past the timeout (it is killed), is unknown. The two ways to answer are
exclusive on one gate, because two answers for one split would need a rule for a conflict, and `limits` mean nothing without a percentage, so a command gate takes none.

**Not the pipeline's pause.** The gate decides only whether the split's tests are held. It does not make `supports_usage_tracking`
true, does not write `paused.json` and does not stop units from starting. A bring-your-own-model runtime that is the build runtime keeps starting
units while its gate holds a split; the units' tier 2 tests in that split park through the hold, as the tier 2 change specifies.

## The burn-rate estimate (optional, out of scope for the groups below)

The library's hourly `billing.report` (one row per object per hour, at most seven days a call) could feed a burn-rate estimate for pacing: the cost in the
last few days divided by the days gone gives a spend per day, and the days the remaining budget lasts could be compared with the days left in the
month, to start the ramp earlier when the month is being spent faster than evenly. It is not needed for the threshold and ramp, which read one number.
It would add a second reader and parser to the provider row, a second cache, and a rule for combining the two, and its value is untested. It is
left out of every group of this change; if wanted it is its own change on top of the provider row.

## Out of scope

- Reading the budget from the provider, redeploying or restarting anything at the provider, and what a provider does when its limit is reached.
- Pausing units or switching runtimes when a provider is over its threshold.
- A gate on anything but a split (a runtime has no gate; the usage windows of the Claude Code runtime are its own).
- A per-start allowance or an estimate for a provider window.
- Other providers than `modal` in the table (a row is a later change); the generic command covers them meanwhile.
- Reading the provider through its command-line tool.
- The burn-rate estimate above.

## UNVERIFIED

- The library's behaviour with no profile and no environment credentials (the exception class and message): the kit treats any exception as unknown
  and prints its class and message, so it does not depend on the text, but the doctor's hint wording does. Task 2.7 checks it with a real call only
  where a login exists.
- That the summary's `start` and `end` stay `datetime` values the parser can compare with an aware clock; the parser accepts a naive one as UTC.
- The held-set file's mechanics until group 4 of `tier2-splits-replace-runtime-tags` is built (above).
- That the cache settings on the gate (`usage_cache_minutes`, `usage_stale_retry_minutes`) instead of under `limits` are what the plan meant by "the ramp under `gate.limits`"; they are on the gate because a command gate has no `limits`.

## Direction note: the test kinds are being renamed

Added while this change is in flight; it changes nothing this change specifies. The two kinds of test, today `tier1` and `tier2`,
are being renamed `unit-test` and `e2e-test` so that "tier" can mean how much review a change gets (see the risk-tiered review
design in the framework repository). The change `test-kind-names-are-accepted-both-ways` adds the layer that reads both spellings,
and group 2 and the groups after it wait for it, so they are built with the new names available.

- Names this change's specs fix (a setting, a tag, a metric) are built as the specs write them. The rename carries them; do not
  rename them by hand and do not edit the spec.
- Anything this change is free to name (a helper, a fake, a test file, a local name) uses the new words.
- If a check rejects an old spelling in a directory the rename has already converted, rename that occurrence to the new spelling,
  keep the behaviour the spec describes, and say so in the commit message. A reviewer reads the new spelling as the same setting as
  the spec's old one.
