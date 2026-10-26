# Tasks

Acceptance: none — every behaviour is proved by a unit-test over a fake runner and temporary git repositories, as the stubbed build's are; nothing a consumer drives is built.

Priority: 0

## 1. [agent-build-kit] [unit-test] A stubbed unit with no commit of its own is satisfied, one with some commits and a missing pair still stops

Priority: 0

Done when a stubbed build whose branch holds no commit of its own after the last group skips the pair-count stop, sets `produced_nothing` and follows `unit_test` to `satisfied` (or the existing failure route when the unit tests fail), a stubbed branch with some commits and a missing pair stops with the pair message naming the first group without a pair, and the old build is as before. Estimate: about 120 changed lines.

- [x] 1.1 Test: in `tests/graph/test_per_group_already_built.py`, over the fake runner and branch fakes of `tests/graph/branch_fakes.py` with the tests and implementation agents writing and committing nothing for any group, a stubbed unit of three groups ends `satisfied` (state `satisfied`, note "nothing to add and unit-test passes — satisfied"), the events show `unit-test` once and no `review`, `push` or `open_pr`, and the branch holds no commit.
- [x] 1.2 Test: the same file asserts the same unit with a failing unit-test ends `failed` with "unit-test failed" and the feedback saved with source `unit-test`, and that a unit with a pull request recorded is satisfied with that pull request closed.
- [x] 1.3 Test: in `tests/graph/test_per_group_partial_commits.py`, a stubbed unit of three groups whose last implementation made no commit (the `no_commit_for="3"` case) still stops with "the branch holds no tests and implementation pair for group 3"; a unit whose first group made nothing and whose second group committed a pair stops after the second group naming group 1, not group 2; and a unit whose tests agent leaves uncommitted files commits them and is not satisfied.
- [x] 1.4 Test: the same pair of files asserts the old build (setting off) over the same fake agents reaches the same `satisfied` state and note for a zero-commit branch, and that a stubbed and an old build over one pre-built base end in one state; the old route's tests (`tests/graph/test_per_group_unstubbed.py`) are unchanged and pass.
- [x] 1.5 Test: in `tests/graph/test_per_group_already_built_resume.py`, a unit stopped earlier with the pair message and requeued with no commit on its branch resumes at `tests` (`existing == 0`), repeats the steps and ends `satisfied`; and a unit whose groups are all test-only (`GroupStep.test_only`) with a tests agent that wrote nothing ends `satisfied` once the sibling change's stub-check advance exists, else this case is skipped with a note naming `a-test-only-group-commits-no-pair/4`.
- [x] 1.6 In `implement`, read `branch_commits` once after the agent and commit steps, skip the pair-count stop when it is 0, return it as `produced_nothing`, and have `unpaired` name the first group the branch lacks a pair for.

## 2. [agent-build-kit] [unit-test] The documents and the changelog say a stubbed unit is satisfied when its work is already built

Priority: 0

Done when `docs/architecture.md` (the stubbed build paragraph and the satisfied outcome after unit-test) and `docs/unit-graph.md` (the `implement` row and its "nothing new" edge) say the stubbed build ends `satisfied` as the old one does when the branch holds no commit of its own, and that a branch with commits and a missing pair still stops; and the changelog has one bullet under `## Unreleased`. Estimate: about 40 changed lines.

- [x] 2.1 Test: in `tests/docs/test_already_built_stubbed_unit_documented.py`, `docs/architecture.md` says a stubbed unit with no commit of its own is satisfied, and a unit with commits and a missing pair stops; the `implement` row of `docs/unit-graph.md` says the stubbed build also ends `unit-test` -> `satisfied` for such a unit; and `CHANGELOG.md` holds the bullet once under `## Unreleased`.
- [x] 2.2 Update both documents and add one changelog bullet under `## Unreleased` as the repository's changelog section says: written for the person, one bullet, a two-space continuation, no unit names or numbers.
