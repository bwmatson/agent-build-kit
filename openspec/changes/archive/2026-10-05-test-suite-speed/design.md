# Design

## The command

`poe test` becomes `pytest -n auto`, capped by a `--maxprocesses` value so a
small CI runner is not oversubscribed. A distribution of `load` (the default)
keeps each test in one worker. `-n auto` is not placed in `addopts`, so
`pytest path/to/test_file.py` stays a single-process run with readable output
and no start-up cost.

## What can break

Parallel runs surface tests that depend on order or on something shared:

- temporary paths keyed by a fixed name instead of `tmp_path`;
- real subprocess tests that bind a port or leave a process behind (the ACP
  adapter's kill tests);
- tests that read or write `$HOME`, the process environment or the working
  directory without restoring it;
- the unit store's lock file, where a test shares one path.

Each is fixed by giving the test its own resource. A test that genuinely needs
exclusivity is marked `serial` and run in a second, single-process pass
(`-m serial` without `-n`), so the whole-suite command stays one invocation
for callers.

## Proof it is stable

The suite is run in parallel many times in a row and in the order reversed
(`-p no:randomly` off and on, if a random-order plugin is added), and the
timing tests that were flaky under load (the process-exit tests) are made
tolerant of load or marked serial. A parallel failure that does not appear
serially is a defect in the test, never retried away.

## Out of scope

Splitting CI into more jobs, caching, and changing what the tests assert.
