# Tasks

Priority: 3

Acceptance: none — every input is a recorded file (readings, ledger, kept result) that the tier-1 tests fabricate; a driven run would need days of real history to mean anything.

## 1. [agent-build-kit] [tier1] The allowance of each window is calibrated from the recorded history

Done when, with enough recorded pairs, an estimate adds the calibrated allowance instead of the flat one, `abk status` prints which allowances are in force and the pairs behind them, and with `calibrate_usage_allowances: false` nothing differs from today. About 450 changed lines.

- [x] 1.1 Test (`tests/pipeline/test_usage_allowances.py`): pairs — consecutive `ok` readings at least `usage_cache_minutes` apart; a fall, a gap longer than the window's span, a gap with no unit that spent, and rows without percentages each make no pair; units are counted by distinct id from agent rows in `[earlier, later)`.
- [x] 1.2 Test: the weekly worked case — twelve pairs with per-unit gains 0, 0, 0.5, 0.5, 0.5, 1, 1, 0.5, 0, 1, 0.5, 2 give 1 at quantile 0.9; a session set of ten pairs between 11 and 14 gives a figure above 10 and no more than 20.
- [x] 1.3 Test: the newest `usage_allowance_window` pairs only; seven pairs against a minimum of eight apply nothing; the floor raises a zero quantile to 1; the ceiling (twice the default under `auto`, the set number otherwise) caps a high one.
- [x] 1.4 Test: configuration — `usage_unit_allowance_pct` accepts a whole number or `auto` and defaults to `auto` with 10 and 2 as the built-in defaults per window; an explicit number is the cap and the fallback; the new keys have their defaults and each bad value fails to load naming the key.
- [x] 1.5 Test: the kept result (`usage-allowances.json`) holds quantile, pairs used, pairs available and time per window; a missing, unreadable or foreign file means defaults and no error; the record is read once per tick however many units are decided.
- [x] 1.6 Test: `_estimates` applies the kept calibrated allowance (reading 70, three units, allowance 1: 73), the configured one when none, and every window's configured one with calibration off.
- [x] 1.7 Test: `abk status` prints `usage allowances: session 9/unit (24 pairs), weekly 1/unit (24 pairs), calibrated`, the defaults line with pairs of needed, and the off line, and makes no call.
- [x] 1.8 Add `pipeline/usage_allowances.py`: the pair-making and `calibrated_allowances` as pure functions, the kept-result read and atomic write, and the bounds applied at use.
- [x] 1.9 Add the settings to `config.py` (`int | "auto"` for `usage_unit_allowance_pct`, the per-window floor, the four calibration keys) with their checks; compute once per tick in `cli/pipeline.py`; read the kept result in `usage_guard._estimates`; print the status line.
- [x] 1.10 Update `docs/configuration.md` (the keys, `auto`, cap and fallback), `docs/architecture.md` (the usage section), the `abk-config` skill's limits block, the comment on `usage_unit_allowance_pct`, and add a changelog entry per the changelog rules in the repo's AGENTS.md.

## 2. [agent-build-kit] [tier1] `abk usage replay` re-runs the estimator over the recorded history

Done when `abk usage replay` prints per usable gap the estimate against the actual reading and per window the counts of underestimates, misses beyond the margin, false pauses and false allows, with no write and no call. About 350 changed lines.

- [x] 2.1 Test (`tests/cli/test_usage_replay.py`): a fabricated record of five weekly gaps prints one underestimate and two false pauses; the rows show the reading before, after, the units and the estimate.
- [x] 2.2 Test: walk-forward — twelve gaps with a minimum of eight use the configured allowance for the first eight and the allowance calibrated from the gaps before each afterwards; `--session-allowance`, `--weekly-allowance` and `--margin` replace them.
- [x] 2.3 Test: `--since` keeps only gaps whose first reading is at or after it; a record with no usable gap prints that and exits 0; a malformed `--since` is refused naming the value.
- [x] 2.4 Test: read-only — the state directory is unchanged after a run, the usage endpoint is not asked and no model is called; the output names the static threshold (the configured pause percent) it judges against.
- [x] 2.5 Add `cmd_usage_replay` and its parser to `cli/usage_cmd.py`, on the pairs and the estimate of group 1 (`usage_allowances.pairs`, `estimate_usage`).
- [x] 2.6 Update `docs/cli.md` (`abk usage replay`, its options and counts), the `abk-pipeline` skill if it lists usage commands, and the changelog bullet from 1.10, folding this command into it.
