## From `tier2-tests-have-their-own-time-limit/1`

- tests/test_tier2_time_limit.py keeps its own `run_child` child-pytest harness beside the one in the existing time-limit test file. The builder's reason holds for this round: this helper also writes a `pytest.ini` that registers `local_stack` and returns the exit code with the output. Merging the two into one shared helper that takes optional ini text could be a later cleanup.
