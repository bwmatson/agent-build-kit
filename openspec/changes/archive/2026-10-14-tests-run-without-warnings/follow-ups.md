## From `tests-run-without-warnings/1`

- The planning repo's test-determinism requirement and design section 'The guard against regressions' still say the pytest options turn the multi-threaded-fork DeprecationWarning into an error. Reword them to describe the `tests.fork_warning_guard` plugin, which records warnings in each test phase and fails the phase on that message.
- tests/fork_warning_guard.py:25 — When the wrapped phase raises (a failing test, setup or teardown), the exception propagates out of the `with` block after `finally` and skips the re-emit loop, so that phase's other warnings never reach pytest's summary.
