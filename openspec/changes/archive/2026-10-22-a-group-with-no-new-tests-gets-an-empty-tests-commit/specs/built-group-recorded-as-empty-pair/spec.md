## MODIFIED Requirements

### Requirement: A group already built is recorded with an empty, marked pair

In a stubbed build (`builders.per_group_commits` on, the repo's profile supporting stubs), when the tests and implementation steps of a group leave nothing
to commit (the head has not moved since the group began and the commit step staged nothing), the branch holds neither commit of the group and holds at
least one commit of its own, the build SHALL check the tree and, when the check passes, record the group with two commits made with `git commit --allow-empty`:
`test: <group title>` and then `feat: <group title>`. The `test:` commit SHALL be made at the end of the tests step (see "A group with no new tests gets an empty
tests commit"), without a test run, and the `feat:` commit after the implementation step and the check. Each SHALL carry the group's usual body, the trailer `Unit: <unit id>` and the trailer
`Already-built: yes`, with the trailers last. The body of the `feat:` commit SHALL also hold the implementation agent's last message, redacted of secrets
and cut to 2,000 characters, as the reason. Position and title matching, resume, restack and the push gate SHALL treat the pair as any other group's.

#### Scenario: Group 4 already built after group 3's pair

- **GIVEN** a stubbed unit of groups 3 and 4 whose group 3 made a real `test:` and `feat:` pair and whose group 4 agents commit nothing, with the unit tests passing
- **WHEN** group 4 is built
- **THEN** the branch ends with `test: <group 4 title>` and `feat: <group 4 title>` holding no file, each with `Unit:` and `Already-built: yes`, the `feat:` body holds the agent's account, the pair count passes and the unit goes on to checks and review

#### Scenario: A group that committed is unchanged

- **GIVEN** a stubbed unit whose every group's agents commit their pair
- **WHEN** it is built
- **THEN** no commit carries `Already-built` and no whole-repository test run is made for a group

#### Scenario: The unit has no commit yet

- **GIVEN** a stubbed unit whose branch holds no commit of its own after a group whose agents commit nothing
- **WHEN** the group ends
- **THEN** nothing is recorded; the existing rule applies, and if no later group commits either, the unit ends `satisfied`

#### Scenario: The account is the reason

- **GIVEN** a group recorded as built whose implementation agent said "Nothing needed changing. The four tests already pass"
- **WHEN** the commit list is read
- **THEN** the `feat:` commit's body holds that sentence and a reader finds `Already-built: yes` in its trailers

#### Scenario: A test-only group already built

- **GIVEN** a stubbed unit with commits whose `[e2e-test]` group's tests agent commits nothing and whose tests pass
- **WHEN** the group is built
- **THEN** one empty `test:` commit with the marker is recorded, no `feat:` commit is, and the group counts as done

#### Scenario: The empty test commit comes first

- **GIVEN** a stubbed unit of groups 3 and 4 whose group 3 made a real pair and whose group 4 agents commit nothing
- **WHEN** group 4's tests step ends and, later, its implementation step ends
- **THEN** the empty `test: <group 4 title>` is on the branch before the implementation agent runs, and the empty `feat: <group 4 title>` is made after it

### Requirement: The group's tests are checked before the pair is recorded

The build SHALL record the `feat:` of an already-built group, or of a group whose real tests pass with no implementation change, only when the whole-repository unit tests pass on the tree.
When they do not pass, it SHALL record no `feat:`, save the output as feedback with the source `unit-test` and stop the unit with "the branch holds no tests and implementation pair for group <n> (<title>)".
A broken environment SHALL block the unit as the unit-test step does and SHALL NOT stop it with that message. The empty `test:` of a group with no new tests is
made without a test run and claims only that the group adds no new tests; it stays on the branch when the unit stops, and a requeue resumes at the group's implementation step.
A group whose `test:` commit holds files and whose `feat:` commit is absent SHALL be recorded only by the rule "Real tests that already pass are completed with an empty feat commit", when those tests pass, and otherwise SHALL stop the unit.

#### Scenario: The tests fail on the tree

- **GIVEN** a stubbed unit with commits whose group 4 agents commit nothing and whose group 4 tests fail
- **WHEN** group 4 is built
- **THEN** no empty `feat:` commit is made, the empty `test:` made at the end of the tests step stays, the unit stops with the pair message for group 4, and the failing output is saved as `unit-test` feedback

#### Scenario: Stubs and tests with no implementation

- **GIVEN** a group whose tests agent wrote stub and test files that were committed (the stubs raise until implemented) and whose implementation agent commits nothing
- **WHEN** the pairs are counted
- **THEN** the whole-repository unit tests fail, the unit stops with the pair message, and nothing is recorded

#### Scenario: A broken environment

- **GIVEN** a group recorded or about to be recorded whose whole-repository run fails because the environment is broken
- **WHEN** the run ends
- **THEN** the unit is blocked as the unit-test step blocks it and is not stopped with the pair message

### Requirement: A killed run resumes between the two empty commits

When the tip of the branch is a marked empty `test:` commit with the title of the group the branch says is next, a resumed stubbed build SHALL run that
group's implementation step as for any part-built group and, after the same check passes when the implementation step changes nothing, record only its empty `feat:` commit; when the
implementation step changes files, the normal `feat:` commit completes the pair. A kill between the empty `test:` made at the end of the tests step and the implementation step SHALL resume the same way.

#### Scenario: Killed between the empty commits

- **GIVEN** a stubbed unit killed after the empty `test:` of group 4 and before its `feat:`
- **WHEN** it is resumed
- **THEN** it resumes at the implementation step of group 4, records the empty `feat:` and goes on, with one pair for group 4 on the branch

#### Scenario: Killed after the empty tests commit, the implementation then changes files

- **GIVEN** a stubbed unit killed after the empty `test: <group 4 title>` made at the end of the tests step and before the implementation step ran
- **WHEN** it is resumed and the implementation agent changes files
- **THEN** the run resumes at the implementation step, the normal `feat: <group 4 title>` is committed, and the branch holds one pair for group 4, `test` empty and `feat` real

### Requirement: The push gate and a restack accept a recorded group

The push gate SHALL accept a branch holding a recorded group: the empty commits are neither tests nor code to the commit-order check, the empty `test:` is not
lint-checked or run red, and the unit's groups are read from the `Unit:` trailer of the tip commit. This holds for an empty `test:` followed by a real `feat:`, an empty
`test:` and `feat:`, and a real `test:` followed by an empty `feat:`. A restack onto a moved base SHALL keep the empty commits with their subjects and trailers. In the
squash merge the empty commits SHALL NOT reach the main branch. The pipeline's own push path SHALL NOT run the gate's red check.

#### Scenario: The gate accepts the empty pair

- **GIVEN** a branch of a real `test:` and `feat:` pair followed by an empty marked pair, over a temporary repository
- **WHEN** the push gate checks it
- **THEN** it reports no problem and makes no clean or red run for the empty `test:` commit

#### Scenario: The gate accepts an empty tests commit and a real implementation commit

- **GIVEN** a branch of a real pair for group 3 followed by an empty marked `test:` and a real `feat:` for group 4, over a temporary repository
- **WHEN** the push gate checks it
- **THEN** it reports no problem and makes no clean or red run for the empty `test:`

#### Scenario: A restack keeps the pair

- **GIVEN** the same branch and a base that has moved
- **WHEN** the branch is moved onto the new base
- **THEN** all four commits are on the branch with their subjects and trailers, and the pair count still finds every group

#### Scenario: A restack keeps an empty tests commit before a real implementation commit

- **GIVEN** the branch of an empty marked `test:` followed by a real `feat:` and a base that has moved
- **WHEN** the branch is moved onto the new base
- **THEN** both commits are on the branch with their subjects and trailers and `group_progress` counts the group done

#### Scenario: A branch of only empty commits

- **GIVEN** a branch whose commits are all empty
- **WHEN** the push gate checks it
- **THEN** it reports "the branch changes no tests and no code"

## ADDED Requirements

### Requirement: A group with no new tests gets an empty tests commit

In a stubbed build, for a group that is not test-only, when the tests step finishes and the static check passes with nothing to commit, the branch already holds at least one
commit of its own, the earlier groups all have their pairs (the pair count is at this group), the branch holds no `test:` of this group and no lone `feat:` of this group, the build SHALL
record an empty `test:` commit for the group at that point, made with `git commit --allow-empty`, with the subject `test: <group title>`, the group's usual body, a sentence that the group adds no
new tests, and the trailers `Unit: <unit id>` and `Already-built: yes` last. It SHALL make no model call and run no tests. The head the implementation step compares against SHALL be the head after that
commit. A branch with no commit of its own, a test-only group, a group whose tests agent committed, and a build with the setting off SHALL record nothing here.

#### Scenario: Group 4 reuses the tests of group 3 and its implementation changes files

- **GIVEN** a stubbed unit of groups 3 and 4 whose group 3 made a real pair, whose group 4 tests agent commits nothing because the tests exist, and whose group 4 implementation agent changes a file
- **WHEN** group 4 is built
- **THEN** the branch subjects are `test: <group 3 title>`, `feat: <group 3 title>`, `test: <group 4 title>`, `feat: <group 4 title>`; the `test:` of group 4 holds no file and carries `Unit:` and `Already-built: yes`; the `feat:` of group 4 holds the file and carries no `Already-built`; the pair count passes and the unit goes on to checks

#### Scenario: Group 4 reuses the tests and its implementation changes nothing

- **GIVEN** the same unit whose group 4 implementation agent changes nothing and whose whole-repository unit tests pass
- **WHEN** group 4 is built
- **THEN** the branch ends with an empty `test:` and an empty `feat:` for group 4, exactly one whole-repository run is made, and the `feat:` body holds the agent's account

#### Scenario: Unit reviewers-are-told-where-to-look/4 as it happened

- **GIVEN** a branch whose history is `test g3, feat g3, feat g4, test g4 (empty, marked), feat g4 (empty, marked)`, left by an earlier attempt whose implementation step changed a changelog blank line and a stale assertion and committed `feat g4` with no `test:` before it
- **WHEN** the pairs are counted for group 4
- **THEN** the unit stops with "a feat: commit for group 4 has no test: commit before it (feat: <group 4 title>)" and not with the generic pair message

#### Scenario: A lone feat commit before the group's tests step

- **GIVEN** a branch `test g3, feat g3, feat g4` and a requeued unit whose group 4 tests agent commits nothing
- **WHEN** group 4's tests step ends
- **THEN** no empty `test:` is made, and after the implementation step the unit stops with the lone-`feat:` message

#### Scenario: A branch with no commit of its own

- **GIVEN** a stubbed unit whose branch holds no commit and whose group 1 tests agent commits nothing
- **WHEN** group 1's tests step ends
- **THEN** no empty `test:` is made and the zero-commit route applies

#### Scenario: A test-only group and a group whose tests agent committed

- **GIVEN** a test-only group whose tests agent commits nothing, and a group whose tests agent committed real tests
- **WHEN** their tests steps end
- **THEN** the test-only group is recorded as the earlier rule says and the other group gets no empty `test:`

#### Scenario: The setting off

- **GIVEN** `builders.per_group_commits` off
- **WHEN** a unit is built
- **THEN** no commit carries `Already-built`

### Requirement: Real tests that already pass are completed with an empty feat commit

In a stubbed build, for a group that is not test-only whose `test:` commit holds files (the tests agent committed real tests) and whose implementation step commits nothing, the build
SHALL run the whole-repository unit tests, which include the group's tests. When they pass, it SHALL record only an empty marked `feat: <group title>` commit, with the trailers `Unit:` and
`Already-built: yes`, whose body says the tests for the group pass without further implementation because the implementation already exists, followed by the agent's account. When they do not pass,
or the run finds a flake, it SHALL record nothing, save the output as `unit-test` feedback and stop the unit with the pair message; a broken environment SHALL block the unit instead. A group whose
implementation step changes files SHALL be unchanged: the normal `feat:` commit is made and no whole-repository run is made for it.

#### Scenario: Real tests that pass, implementation empty, suite passes

- **GIVEN** a stubbed unit whose group 12 tests agent committed five real tests that pass because group 11's implementation covers them, whose implementation agent changes nothing, and whose whole-repository unit tests pass (unit `a-unit-over-its-tier-is-held-and-split/13`)
- **WHEN** group 12 is built
- **THEN** the branch holds the real `test: <group 12 title>` and an empty `feat: <group 12 title>` marked `Already-built: yes` whose body says the tests pass without further implementation, the pair count passes and the unit goes on to checks

#### Scenario: Real tests, implementation empty, suite fails

- **GIVEN** a group whose tests agent committed real tests that fail (stubs that raise until implemented) and whose implementation agent commits nothing
- **WHEN** group is built
- **THEN** no `feat:` is recorded, the unit stops with "the branch holds no tests and implementation pair for group <n> (<title>)", and the output is saved as `unit-test` feedback

#### Scenario: Real tests, implementation makes changes

- **GIVEN** a group whose tests agent committed real tests and whose implementation agent changes files
- **WHEN** the group is built
- **THEN** the normal `feat:` commit is made, nothing carries `Already-built`, and no whole-repository run is made for the group

#### Scenario: The push is not blocked by a green tests commit

- **GIVEN** a recorded group of a real, passing `test:` and an empty `feat:`
- **WHEN** the pipeline pushes the unit's branch
- **THEN** the pipeline's push path does not run the gate's red check (`check_branch` is called only by `abk gate`) and the push condition is the approved SHA, as for any unit

### Requirement: A lone implementation commit is named when its tests commit is missing

When the pair count finds, where a group's `test:` commit was expected, a `feat:` commit with that group's title, the unit SHALL stop with "a feat: commit for group <n> has no test: commit before it",
followed by that commit's subject in parentheses. Every other missing-pair stop SHALL keep its existing text.

#### Scenario: A lone feat commit where a tests commit was expected

- **GIVEN** a branch `test g3, feat g3, feat g4` in a unit of groups 3 and 4
- **WHEN** the pairs are counted for group 4
- **THEN** the stop reads "a feat: commit for group 4 has no test: commit before it (feat: <group 4 title>)"

#### Scenario: Any other missing pair

- **GIVEN** a branch with a real `test:` of group 4 and no `feat:` after it, and failing unit tests
- **WHEN** the pairs are counted
- **THEN** the stop reads "the branch holds no tests and implementation pair for group 4 (<title>)"
