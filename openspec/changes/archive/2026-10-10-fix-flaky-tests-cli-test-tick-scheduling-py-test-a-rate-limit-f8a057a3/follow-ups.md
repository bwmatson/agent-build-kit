## From `fix-flaky-tests-cli-test-tick-scheduling-py-test-a-rate-limit-f8a057a3/1`

- In `_may_build` (src/agent_build_kit/cli/pipeline.py), the line 'resuming a pause that was to last until …' is logged before `clear_pause` reports whether a rate-limit pause recorded since is being kept. Log it only once `clear_pause` returns None, so the tick log does not report a resume that never happened.
- src/agent_build_kit/cli/pipeline.py:917 — When the round started under a usage pause and a rate-limit pause is recorded while it decides, the round logs 'resuming a pause that was to last until …' and then immediately logs the rate-limit pause line. The resume line is logged before `clear_pause` reports whether anything was actually resumed.
