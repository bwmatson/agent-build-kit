# Tasks

Acceptance: none — every behaviour is proved by a unit-test over temporary git repositories, fake agents and fake profiles, as the parent change's are; nothing a consumer drives is built, and a real-model run of the stubbed build is what the soak of `builders.per_group_commits` measures.

Priority: 0

## 1. [agent-build-kit] [unit-test] A group is test-only when its heading says `[e2e-test]`

Priority: 0

Done when a parsed task group can be asked whether it is test-only (true for an `[e2e-test]` group, flagged `[acceptance]` or not, and for no other), and the per-group build step of a unit carries the answer for each group, false for a group whose heading cannot be read. Estimate: about 90 changed lines.

- [x] 1.1 Test: in `tests/pipeline/test_task_group_test_only.py`, a group headed `[app] [e2e-test] [acceptance]` is test-only, and so is a plain `[app] [e2e-test]` group with no flag, an `[e2e-test] [contract]` group and an `[e2e-test] [narrow]` group; none of these is: a `[unit-test]` group whose tasks are all `Test:` tasks, and an `[integration-test]` group.
- [x] 1.2 Test: in `tests/pipeline/test_group_steps_test_only.py`, over a temporary change directory, the steps of a unit holding a `[unit-test]` group and an `[e2e-test]` group report the second as test-only and the first not, in the unit's order, including a unit that carries groups of another change; a group number missing from `tasks.md` is not test-only.
- [x] 1.3 Make the parsed group expose the answer from its tier and flag, and the per-group step carry it.

## 2. [agent-build-kit] [unit-test] The commit-order check accepts a test-only group's lone tests commit and nothing else

Priority: 0

Done when the commit-order check, given the unit's groups in order with their test-only answers, accepts a `test:` commit with no `feat:` after it only when it is the commit of a test-only group, still refuses every other unpaired `test:` commit, does not report two tests commits in a row after a test-only commit, does not ask for an implementation commit of a unit whose groups are all test-only, and with no groups given is as before. Estimate: about 220 changed lines.

- [x] 2.1 Test: in `tests/pipeline/test_commit_order_test_only.py`, over temporary repositories, in paired mode with the plan given, a branch `test: A`, `feat: A`, `test: Drive` passes when "Drive" is test-only (last), and `test: A`, `feat: A`, `test: B` is refused naming `test: B` and `feat: B` when B is not test-only (a lone test commit of an ordinary group).
- [x] 2.2 Test: the same file asserts a test-only commit in the middle (`test: A`, `feat: A`, `test: Drive`, `test: C`, `feat: C`) passes with no "two tests commits in a row"; `test: B` followed by `feat: C` is refused naming both titles when B is not test-only; a test-only commit followed by a `fix:` commit passes; and two groups with one title are told apart by their position in the plan.
- [x] 2.3 Test: the same file asserts a branch of one `test:` commit per group with every group test-only passes with no "no implementation commit" problem, the same branch with one group not test-only (and no `feat:`) is refused, and a branch with no plan given and a lone `test:` commit is refused as before, as is every case of the parent change's `tests/pipeline/test_commit_order_pairs.py`.
- [x] 2.4 Make the structure check take the unit's groups and apply the three exceptions above by the group's position, for the paired mode.

## 3. [agent-build-kit] [unit-test] The push gate asks no red run of a test-only group's tests commit, and reads the plan

Priority: 0

Done when the push gate runs lint, format and types but no red command at a test-only group's tests commit and reads the red run at every other tests commit as before, keeps a test-only commit's cached result apart from the others, and `abk gate` in an installation takes the groups from the unit named by the branch's `Unit:` trailer, with no groups known outside one. Estimate: about 260 changed lines.

- [x] 3.1 Test: in `tests/pipeline/test_gate_test_only.py`, with fake profiles and commands, the gate for a stubbed build over a test-only group's `test:` commit that holds only `local_stack` tests runs the clean command with types and does not run the red command, and is not refused when the red command would have collected nothing ("no tests ran") or failed on a refused connection (an unrecognised failure).
- [x] 3.2 Test: the same file asserts the same branch's ordinary `unit-test` group, whose tests pass at its tests commit, is still refused for "nothing failed at the tests commit", that an ordinary group's `local_stack`-only commit is judged by the red run as today, and that a test-only commit that fails the type check is refused naming the commit.
- [x] 3.3 Test: in `tests/pipeline/test_check_cache_test_only.py`, a result cached for a commit judged with no red run is not reused when the same patch is judged as an ordinary tests commit, and the reverse; a result cached for a test-only commit is reused by the next run after a restack.
- [x] 3.4 Test: in `tests/cli/test_gate_plan.py`, `abk gate` in an installation on a branch whose commits carry the `Unit:` trailer of a unit with an `[e2e-test]` group last accepts the lone `test:` commit; on the same branch with no trailer, or outside an installation, it refuses it; and with the setting off it runs today's gate unchanged.
- [x] 3.5 Skip the red command and its reading for a test-only commit, key its cached result by a mode of its own, and have `abk gate` read the unit's groups from the trailer through the same per-group read the build uses.

## 4. [agent-build-kit] [unit-test] A stubbed build commits a test-only group's tests alone and counts, resumes and routes it

Priority: 0

Done when a stubbed build makes one `test:` commit for a test-only group after the static checks, makes no implementation call for it, goes on to the next group's tests or to the checks, counts the group as satisfied by that commit, resumes by the branch with the group done once its commit is there, and still stops a unit whose ordinary group has no implementation. Estimate: about 420 changed lines.

- [x] 4.1 Test: in `tests/graph/test_test_only_group_build.py`, with a fake agent that records its prompts, a stubbed build of an ordinary group and a test-only group gives agent calls in the order tests of group 1, implementation of group 1, tests of group 2 and no more, the branch reads `test: <1>`, `feat: <1>`, `test: <2>`, the test prompt of group 2 says the group builds no implementation, needs no stubs and is not to run live-stack tests, and the build goes on to the checks.
- [x] 4.2 Test: the same file asserts a test-only group in the middle gives tests of group 1, implementation of group 1, tests of group 2, tests of group 3, implementation of group 3 and the matching branch, that a unit of only test-only groups gives one tests call and one `test:` commit per group, no implementation call and no stop for a missing implementation, and that a failing static check on a test-only group's tests is handed back to the test agent and the commit is made only after it passes.
- [x] 4.3 Test: in `tests/graph/test_test_only_group_pair_count.py`, a full count with a test-only last group goes on to the checks, an ordinary last group whose implementation made no commit stops the unit with "the branch holds no tests and implementation pair for group <n> (<title>)", a `[unit-test]` group holding only tests, with no implementation commit, stops it the same way, and a short count with a test-only last group (an earlier group missing its pair) names the earlier group.
- [x] 4.4 Test: in `tests/graph/test_test_only_group_resume.py`, a branch holding group 1's pair and group 2's (test-only) `test:` commit resumes at the checks and writes nothing; a branch holding only group 1's pair resumes at group 2's tests and not at an implementation; a branch killed in the stub check loop of the test-only group resumes at the fix with the rounds counted; a restack that rewrote every hash resumes the same; and two groups with one title are told apart by position.
- [x] 4.5 Test: in `tests/pipeline/test_group_progress_test_only.py`, the progress walk over subjects takes one subject for a test-only group and two for another, reports a test-only group's `test:` commit as done and never as tests-made-awaiting-implementation, and is as before when no group is test-only.
- [x] 4.6 Make the tests step's prompt for a test-only group, have the stub check step commit the group's tests commit and advance the group as the implement step does, route past the implement step, count satisfied groups after the last group (including at the end of the stub check step), and read the plan's test-only answers in the progress walk used by resume.

## 5. [agent-build-kit] [unit-test] The documents, the authoring skill and the changelog describe test-only groups

Priority: 0

Done when `docs/architecture.md` (the stubbed build paragraph and the push gate paragraph), `docs/unit-graph.md` (the `stub_checks` and `implement` rows and the graph edges), `docs/cli.md` (`abk gate`), the `abk-authoring` skill source (the `[e2e-test]` tag) and the `abk-pipeline` skill source say what a test-only group is and how it is committed, counted and gated, and the changelog has one bullet under `## Unreleased`. Estimate: about 150 changed lines.

- [x] 5.1 Test: in `tests/docs/test_test_only_group_documented.py`, `docs/architecture.md` names a test-only group, its lone `test:` commit, the skipped implement step, the pair count and the gate's exception and no-red-run rule; `docs/unit-graph.md` shows the edge from `stub_checks` past `implement`; `docs/cli.md`'s `abk gate` section says the gate reads the unit's groups from the `Unit:` trailer; the `abk-authoring` skill says an `[e2e-test]` group, flagged `[acceptance]` or not, is committed as one `test:` commit in a stubbed build and that a `[unit-test]` or `[integration-test]` group of tests still needs its implementation; the `abk-pipeline` skill's stub-check paragraph names the lone commit; and `CHANGELOG.md` has the bullet once under `## Unreleased`.
- [x] 5.2 Update the documents and the two skill sources named above (the setting is named as `builders.per_group_commits`; the rename carries through), and add one changelog bullet under `## Unreleased` as the repository's changelog section says: written for the person, one bullet, a two-space continuation, no unit names or numbers.
