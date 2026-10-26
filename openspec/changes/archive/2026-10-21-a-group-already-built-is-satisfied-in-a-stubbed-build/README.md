# a-group-already-built-is-satisfied-in-a-stubbed-build

Unit `reviewers-are-told-where-to-look/4` (repo agent-build-kit) failed on 2026-10-21 with `the branch holds no tests and implementation pair for
group 4 (The Start here section is never shrunk, and a held unit carries it)`. Group 4's work (two test files and `pipeline/pr_body.py`) was already
on the base, built by group 3's unit, so the agent rightly wrote and committed nothing ("new copies of passing tests would break the rule that a new
test must fail first"). With `builders.per_group_commits` off that outcome ends the unit `satisfied`, with nothing committed (`implement` sets
`produced_nothing`, `after_implement` sends it to `unit_test`, `after_unit_test` to `satisfied`). With it on, `implement` runs the pair count first
and stops the unit before `produced_nothing` is set, so an already-built unit can never be satisfied. This change makes the stubbed build skip
the pair-count stop when the branch has no commit of its own over its base, set `produced_nothing`, and follow the existing route
`unit_test` -> `satisfied`. A unit with some commits of its own and a missing pair still stops with the pair message. Both flows stay behind the
setting; the setting off is untouched. Emergency lane (priority 0).
