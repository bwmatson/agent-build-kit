# Tasks

Acceptance: none — this changes how the pipeline builds a unit and how its push gate reads the branch, and every behaviour is proved by a unit-test over temporary git repositories, fake agents and fake profiles; nothing a consumer drives is built, and a real-model run of the new loop is what the soak in the design measures.

Priority: 1

## 1. [agent-build-kit] [unit-test] Profiles declare stub support and a types-inclusive clean check

Done when a profile can be asked whether it supports stubs (python-uv and node-npm do, one that says nothing does not), the clean check can be asked with types for each of them, and with neither asked every profile behaves as before. Estimate: about 240 changed lines.

Needs: test-kinds-are-unit-test-and-e2e-test group 23 — the test kinds are renamed first, so the profile methods and the new nodes are written once in the new names

- [x] 1.1 Test: in `tests/profiles/test_stub_support.py`, python-uv and node-npm report that they support stubs, a profile object with no such attribute reports that it does not, and a profile that says false reports false.
- [x] 1.2 Test: in `tests/profiles/test_python_uv_types_check.py`, the clean command without the types flag is unchanged and skips the type hook, and with it the command runs every hook including the type check.
- [x] 1.3 Test: in `tests/profiles/test_node_npm_types_check.py`, the clean command without the flag is lint and the format check as before, and with it the project's `tsc --noEmit` is also run in the same shell string.
- [x] 1.4 Add the stub-support declaration to the profile protocol with a helper that reads it tolerantly, and the types flag on the clean command, with the python-uv and node-npm implementations. (First part of the old task; the stubbed reading of red is in the next group.)

## 2. [agent-build-kit] [unit-test] Profiles read red in a stubbed mode

Done when the red reading can be asked in a stubbed mode that accepts only an assertion or `NotImplementedError` in a test body, for a JUnit report, a Vitest report and the console fallback, and with it not asked every profile reads red as before. Estimate: about 300 changed lines.

- [x] 2.1 Test: in `tests/profiles/test_python_uv_stubbed_checks.py`, a stubbed reading of a JUnit report rejects a test that failed with `ModuleNotFoundError`, `ImportError` or `AttributeError` naming the test while the unstubbed reading still accepts it, and both accept `AssertionError` and `NotImplementedError` and reject a passing test.
- [x] 2.2 Test: in `tests/profiles/test_node_npm_stubbed_checks.py`, the stubbed reading of a Vitest report rejects a suite that failed to load and a passing test and accepts an assertion failure and a "not implemented" error.
- [x] 2.3 Test: in `tests/pipeline/test_red_check_stubbed.py`, the console fallback read in stubbed mode rejects output whose only failure markers are import, module or attribute errors, names the marker, and with a JUnit report the exception type of each failing test decides.
- [x] 2.4 Add the stubbed flag on the red reading, with the python-uv and node-npm implementations, and a stubbed reading in the red-check module. (Second part of the old task.)

## 3. [agent-build-kit] [unit-test] The setting, and a paired mode of the commit-order check

Done when `builders.per_group_commits` loads as a boolean with a default of off for now, a stubbed build is reported only when the setting is on and the profile supports stubs, and the commit-order check has a paired mode that refuses a `test:` commit not directly followed by a `feat:` commit of the same title and is unchanged when not asked. Estimate: about 250 changed lines.

- [x] 3.1 Test: in `tests/config/test_builders_per_group_commits.py`, a workspace with no `builders` section loads with the setting off, a boolean loads as given, a string fails loading naming `builders.per_group_commits`, and a stubbed build is reported only when the setting is on and the profile supports stubs.
- [x] 3.2 Test: in `tests/pipeline/test_commit_order_pairs.py`, over temporary repositories, a branch of two correct pairs passes the paired check, two `test:` commits in a row is reported naming the second, a `test:` commit followed by a `feat:` commit with another title is reported naming both titles, a tests commit holding logic is still reported as today, and an unstubbed branch of one pair passes with the paired check on.
- [x] 3.3 Add the setting to the builders section of the configuration and the paired mode to the commit-order check. (First part of the old task; the gate, `abk gate` and the cache are in the next group.)

## 4. [agent-build-kit] [unit-test] A push gate that reads a stubbed build's types and red

Done when the push gate for a stubbed build refuses a tests commit that fails types, a pair that is not paired, and a red that is not for the right reason, judging each tests commit on its own, caches results by mode, and for a build that is not stubbed behaves as before. Estimate: about 380 changed lines.

- [x] 4.1 Test: in `tests/pipeline/test_gate_stubbed.py`, with fake profiles and commands, the gate for a stubbed build runs the clean command with types and the stubbed red reading at each tests commit and names the commit that fails, judges the second group's tests commit on its own when the first is correct, and for a build that is not stubbed runs what it ran before.
- [x] 4.2 Test: in `tests/pipeline/test_check_cache_mode.py`, a result cached for a tests commit by an unstubbed run is not reused by a stubbed run of the same patch, and a result cached by a stubbed run is reused by the next stubbed run after a restack.
- [x] 4.3 Test: in `tests/cli/test_gate_stubbed_setting.py`, `abk gate` in an installation with the setting on and a stubbed profile runs the stubbed checks, and with the setting off or an unsupported profile runs the unstubbed ones.
- [x] 4.4 Add the stubbed mode to the gate and to `abk gate`, and the mode to the cache's key. (Second part of the old task.)

## 5. [agent-build-kit] [unit-test] The test step is followed by a check-and-fix loop bounded by `max_check_rounds`

Done when in a stubbed build, the test agent's work is checked for lint, format and types before the tests commit, a failure is handed back to the test agent with the checker's output, the loop is bounded by `max_check_rounds` with a counter of its own, a unit still failing stops with the output kept and nothing implemented, and with the build not stubbed the path is as before. Estimate: about 430 changed lines.

- [x] 5.1 Test: in `tests/graph/test_stub_check_loop.py`, with a fake agent and a fake profile, a stubbed build whose checks pass makes the tests commit and goes to the implementation, a failing check hands its output to the test agent with a fix prompt and runs the checks again, a new unstaged file is checked, and no test is executed.
- [x] 5.2 Test: in `tests/graph/test_stub_check_rounds.py`, with `max_check_rounds` 2 a stub failing after each fix stops the unit after two fixes with the last output on the unit, no tests commit and no implementation call; 0 stops at the first failure; null never stops on count; a fix that changed nothing stops the unit; and a second group's loop starts again from zero.
- [x] 5.3 Add the two steps after the test step to the build path with their routing, a fix prompt that carries the checker's output, the round counter on the run's state, and the step's commit of the tests commit in a stubbed build in place of the test step's own commit. (First part of the old task; the feedback source, its routing on resume and the prompts' wording are in the next group.)

## 6. [agent-build-kit] [unit-test] The loop resumes on a requeue and its prompts say what a stub is

Done when a unit stopped in the loop has its output saved under a feedback source of its own, a requeue resumes in the loop, a run killed in a fix resumes with the rounds counted, and the tests prompt asks for stubs that pass those checks while the prompt of a build that is not stubbed is identical to today's. Estimate: about 330 changed lines.

- [x] 6.1 Test: in `tests/graph/test_stub_check_resume.py`, a unit stopped in the loop has its output saved under the new feedback source, a requeue goes to the test step and not to rework and the next agent call is the fix, a run killed in a fix resumes with the rounds counted, and a unit with ordinary review feedback still goes to rework.
- [x] 6.2 Test: in `tests/pipeline/test_stub_check_prompts.py`, the tests prompt of a stubbed build says the stubs and tests must pass lint, format and types, that stubs hold no logic, and that the new tests are not to be run to make them pass; the fix prompt carries the checker's output, says to fix the cause and not to suppress a rule or loosen a type, and says not to change what the tests assert; the prompt of a build that is not stubbed is identical to today's.
- [x] 6.3 Add the new feedback source and its routing on resume, and the prompts' wording. (Second part of the old task.)

## 7. [agent-build-kit] [unit-test] The build writes a tests and an implementation commit for each task group in order

Done when a stubbed build of a unit with several groups writes the tests of one group, passes them through the check loop, commits `test: <group title>`, writes that group's implementation, commits `feat: <group title>`, and does the same for the next, with the unit trailer kept, the checks and review coming after the last group, and a build that is not stubbed still making one pair. Estimate: about 400 changed lines.

- [x] 7.1 Test: in `tests/graph/test_per_group_build.py`, with a fake agent that records its prompts, a unit of three groups gives agent calls in the order tests of group 1, implementation of group 1, tests of group 2, and so on, each prompt naming only its own group, and the branch holds six commits whose subjects are `test: <title>` and `feat: <title>` of each group in order.
- [x] 7.2 Test: in `tests/graph/test_per_group_unstubbed.py`, with the setting off, or on and a profile that does not support stubs, a unit of three groups gets one `test:` and one `feat:` commit titled with the unit's title and the prompts name all three groups, as before.
- [x] 7.3 Make the routing after the implementation step go back to the test step while a group has no pair, and scope the test and implementation prompts and the commit subjects to the group in a stubbed build. (First part of the old task; the bodies and the carried groups are in the next group.)

## 8. [agent-build-kit] [unit-test] Per-group commits say why, and carried groups are built in order

Done when each commit's body has the fixed sentence for what it holds and the group's "Done when" sentence when it has one, and a unit that carries groups of another change builds its own change's groups first and then the carried ones, one pair each. Estimate: about 270 changed lines.

- [x] 8.1 Test: in `tests/graph/test_per_group_commit_messages.py`, a commit's body has the fixed sentence for what it holds and the group's "Done when" sentence when it has one, a group without one has the fixed sentence alone, and every commit keeps the `Unit:` trailer.
- [x] 8.2 Test: in `tests/graph/test_per_group_carried_groups.py`, a unit that carries groups of another change builds its own change's groups first and then the carried ones, one pair each, naming each group's own change directory in its prompt.
- [x] 8.3 Scope the commit bodies to the group, and read the groups from the unit in the order the scope lists them. (Second part of the old task.)

## 9. [agent-build-kit] [unit-test] A stubbed build resumes at the first group without its pair

Done when the group a stubbed build is on is read from the branch, so a killed run, a restack and a requeue continue at the first group whose implementation commit is missing without writing earlier groups again, and a last commit that is a tests commit resumes at that group's implementation. Estimate: about 290 changed lines.

- [x] 9.1 Test: in `tests/graph/test_per_group_resume.py`, a branch with two complete pairs of three groups resumes at the third group's tests, a branch whose last commit is a group's `test:` commit resumes at that group's implementation and writes no tests, a branch with every pair goes to the checks, and a restack that rewrote every commit's hash still resumes at the right group because the subjects are read.
- [x] 9.2 Test: in `tests/graph/test_per_group_duplicate_titles.py`, two groups with the same title are told apart by their position in the unit, so a branch holding the first group's pair resumes at the second.
- [x] 9.3 Read the group a build is on from the branch's subjects in the order of the unit's groups, and resume the test and implementation steps from it. (First part of the old task; the pair count is in the next group.)

## 10. [agent-build-kit] [unit-test] A stubbed build counts its pairs, and rework of a finished branch is as before

Done when the pair count is checked after the last group, and a count short of the groups stops the unit naming the groups missing, and review and rework of a finished branch are as before. Estimate: about 220 changed lines.

- [x] 10.1 Test: in `tests/graph/test_per_group_pair_count.py`, a last implementation that made no commit stops the unit naming the group, a full count goes on to the checks, and a unit that is not stubbed is counted as before.
- [x] 10.2 Test: in `tests/graph/test_per_group_rework.py`, a rework of a unit built per group adds its `fix:` commits after the last pair as today, review sees the whole branch, and the pairs of the groups already built are not written again when the unit is requeued with review feedback.
- [x] 10.3 Add the pair count check after the last group, stopping with the groups missing. (Second part of the old task.)

## 11. [agent-build-kit] [unit-test] The documents and the skills describe stubs, the loop and per-group commits

Done when the architecture and graph documents show the two new steps and the per-group path, the configuration document and the `abk-config` skill describe `builders.per_group_commits` and its default, the toolchain-profiles document says what a profile declares and runs for stubs, `docs/cli.md` says what `abk gate` checks for a stubbed build, the `abk-pipeline` skill explains a unit stopped in the loop, and a document test keeps each of them from drifting. Estimate: about 330 changed lines.

- [x] 11.1 Test: in `tests/docs/test_per_group_commit_docs.py`, `docs/configuration.md` and the `abk-config` skill name `builders.per_group_commits`, `docs/unit-graph.md` names both new steps, `docs/toolchain-profiles.md` names the stub-support declaration, the types flag and the stubbed red reading, `docs/cli.md` describes the gate's paired and types checks, and the `abk-pipeline` skill names the new feedback source and what a requeue does.
- [x] 11.2 Update the documents and the skills' text, and add a changelog entry saying the build can commit per group behind a setting, what the setting does and how to turn it off.

## 12. [agent-build-kit] [unit-test] Stubbed TDD commits are on by default, under the name `stubbed_tdd_commits`

Done when the setting is named `builders.stubbed_tdd_commits` and defaults to on, the old name `builders.per_group_commits` still loads with a deprecation notice and `abk config --migrate` moves it, a workspace with no `builders` section builds with stubs, the check loop and per-group commits, setting it off gives today's build, `abk init`'s template and the documents say on under the new name, and the changelog records the soak figures the design asks for. Estimate: about 450 changed lines (the old name is read in about seventeen files of code, tests and documents).

- [x] 12.1 Test: in `tests/config/test_builders_stubbed_tdd_commits_default.py`, a workspace with no `builders` section reports `stubbed_tdd_commits` on, an explicit off reports off and builds one pair, and the `abk init` template and `docs/configuration.md` state the default as on under the new name. The same file asserts that `builders.per_group_commits` still loads and is read as the new key with a deprecation notice from `abk config` and `abk doctor`, that a file setting both names is refused naming both, that `abk config --migrate` rewrites the old key (including a workspace file that sets it `true` or `false`) to the new one and changes nothing else, and that a string value is refused naming the key under either name.
- [ ] 12.1a Rename `per_group_commits` to `stubbed_tdd_commits` everywhere it is read or documented (`config.py`, `profiles/base.py`, `docs/architecture.md`, `docs/cli.md`, `docs/configuration.md`, `docs/toolchain-profiles.md`, the `abk-config` and `abk-pipeline` skill sources, and the tests that name it, among them `tests/config/test_builders_per_group_commits.py`, `tests/cli/test_gate_stubbed_setting.py`, `tests/docs/test_per_group_commit_docs.py`, `tests/graph/test_per_group_rework.py`, `tests/graph/test_per_group_unstubbed.py` and `tests/pipeline/test_stub_check_prompts.py`, whose files and test names change with it). Register the old key with the deprecated names `abk config --migrate` already moves (as the root key `limits` is for `global_limits`) so a workspace file that names it keeps loading. Do not rename the `per-group-commits` capability or the commit shape; only the setting.
- [x] 12.2 Change the default (on), the template and the documents, remove the earlier group's assertion that the default is off, and add the changelog entry with the units built, how many held several groups, how many the push gate refused for a type or red reason and how many stopped at the loop's round limit, read from the installation that ran the soak; the group is not built until those figures meet the criterion in the design.
