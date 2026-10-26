## From `a-failed-unit-resumes-when-its-wait-ends/1`

- `WAIT_ENDED = "its wait ended"` is defined in both `cli/pipeline.py` and `tests/wait_end_support.py`. The test helper could import `cli.WAIT_ENDED` so the two cannot drift apart. As things stand, the tests would catch a change to the wording, so this is not a correctness issue.
- Group 2 documents `global_limits.wait_end_requeue` in `docs/configuration.md` and the `abk-config` skill, as AGENTS.md asks for every new setting. Until that unit lands, the setting is described only in the changelog.
