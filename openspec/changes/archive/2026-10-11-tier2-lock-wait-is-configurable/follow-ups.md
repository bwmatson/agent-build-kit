## From `tier2-lock-wait-is-configurable/1`

- tests/pipeline/test_tier2_lock_wait_setting.py:38 — WaitClock is a second fake monotonic clock beside FakeClock in tests/fake_clock.py:17. It also swaps out the whole `time` module in tier2, which is why it carries a `strftime` shim, needed because stack_lock writes `time.strftime` into the lock file at tier2.py:113.
