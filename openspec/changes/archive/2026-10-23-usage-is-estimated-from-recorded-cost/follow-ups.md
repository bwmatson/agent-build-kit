## From `usage-is-estimated-from-recorded-cost/1`

- src/agent_build_kit/pipeline/usage_allowances.py:83 — `Calibrated.reason` is a free `str`, and the value read from a file of the previous shape is spelled `"previous file"` (line 411). Every other reason is a snake_case token: `too_few_pairs`, `too_few_judged`, `more_false_allows`, `no_fit`, `basis_units`.
- src/agent_build_kit/config.py:342 — The session window gets its intercept on by default only in a `mode="before"` validator that runs when `session` is a dict. A window passed in as a `UsageWindowConfig` instance keeps that class's default, which is off.

## From `usage-is-estimated-from-recorded-cost/4-s1`

- src/agent_build_kit/pipeline/usage_guard.py:1276 — The rule that decides whether a window's cost fit is in force (a kept entry with `basis == "cost"` and `points_per_usd`, calibration on, and the window's `usage_estimate_basis` set to `cost`) is written inline in the `spend` closure in `_estimates`. It is not a named function in `usage_allowances.py` beside `allowance_for`.

## From `usage-is-estimated-from-recorded-cost/4-s2`

- In allowances_line, `kept is not None and cost_basis_in_force(window, kept, limits)` and the guard's `(found.points_per_usd or 0.0)` are only there so the type checker can narrow the value. Making `cost_basis_in_force` a TypeGuard, or having it return the fit itself (`float | None`), would remove that redundant check and the `or 0.0` fallback.

## From `usage-is-estimated-from-recorded-cost/4-s3`

- The `abk status` section of docs/cli.md now puts the new allowances paragraph before the paragraph that opens 'Prints whether the pipeline is paused…'. Moving it after that paragraph would make the section read summary first, then detail.
