## From `a-refused-usage-read-with-headroom-does-not-pause/1`

- Tracks are admitted under `track:<phase>` (tracks/runner.py:807). If a track's usage-ledger records carry a different unit id, `_estimates` counts that track twice: once as admitted and once as spent. That errs on the safe side, so it does not block. Either key the admission to the id the track writes to the ledger, or add a test that pins the dedupe for tracks.

## From `a-refused-usage-read-with-headroom-does-not-pause/2`

- Call records are still built by hand in `refused()` in tests/usage_host.py and in tests/pipeline/test_usage_climb.py, as well as by `line()` in tests/pipeline/test_usage_calls.py. These copies predate this change. Folding them into one shared helper would leave a single place that knows the shape of a usage-calls.jsonl record.
