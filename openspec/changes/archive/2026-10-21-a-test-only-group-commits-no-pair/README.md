# a-test-only-group-commits-no-pair

Unit `asr-streaming-service/10` (repo <redacted>) failed on 2026-10-21 with `the branch holds no tests and implementation pair for group 10
(Drive the service as a client)`. Group 10 is `[<redacted>] [e2e-test] [acceptance]`: its tasks only add live-stack acceptance tests against code
groups 1-9 built, so there is no implementation to commit; the agent made the tests commit and rightly "made no implementation changes", and the
stubbed build's pair count (`builders.per_group_commits`, soon `stubbed_tdd_commits`) stopped the unit. Here a **test-only group** (a group tagged
`[e2e-test]`, flagged `[acceptance]` or not, read from the plan with no model call; the sibling change `e2e-groups-hold-tests-and-stand-alone`
makes every e2e group hold only tests and test support) is built as ONE `test: <title>` commit and no `feat:` commit: its implement step
is skipped, no red run is demanded of its live-stack tests, the pair count counts the lone commit as satisfying the group, and the push gate accepts a
`test:` commit with no `feat:` after it only when the plan says its group is test-only. Resume reads the group from the branch as before. Emergency
lane (priority 0).
