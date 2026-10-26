## From `usage-allowances-are-calibrated/1`

- usage_report.py keeps its own p90 beside the new nearest-rank quantile in usage_allowances.py. A shared nearest-rank helper would mean one rounding rule to keep in step. The builder deferred this as outside the change.

## From `usage-allowances-are-calibrated/2`

- tests/usage_allowance_records.py:42 — The docstring of `gaps` still says the gaps are 'laid out as `segments` lays out its own', but `segments` now just calls `gaps`, so the sentence points the wrong way.
- CHANGELOG.md:28 — The Unreleased bullet for `abk usage replay` lists the four counts but not the mean overshoot, the not-enough-to-judge note, or the closing `usage allowances:` line that the command now prints.
