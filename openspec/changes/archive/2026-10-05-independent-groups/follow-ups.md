## From `independent-groups/1`

- `_check_independent` now checks two separate rules: an independent unit stands alone, and a narrowing unit waits for the independent units. A separate `_check_narrowing` beside `_check_acceptance` would read more clearly than one loop with an early `continue` that only applies to the second rule.
