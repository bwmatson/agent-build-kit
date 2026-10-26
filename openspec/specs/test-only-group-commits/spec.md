# test-only-group-commits Specification

## Purpose
TBD - created by archiving change a-test-only-group-commits-no-pair. Update Purpose after archive.

## Requirements

### Requirement: A test-only group is decided from its heading

A task group SHALL be test-only exactly when its heading tags it `[e2e-test]`, whether or not it is flagged `[acceptance]`. The decision SHALL be
made from the parsed heading with no model call and SHALL be available to the build, the resume and the push gate from the plan. A group that is
tagged `unit-test` or `integration-test`, even one whose tasks are all tests, and a group whose heading cannot be read SHALL NOT be test-only,
whatever its tasks say.

#### Scenario: An acceptance group is test-only

- **GIVEN** a group headed `## 10. [<redacted>] [e2e-test] [acceptance] Drive the service as a client`
- **WHEN** the group is parsed
- **THEN** it is test-only

#### Scenario: A plain e2e group is test-only

- **GIVEN** a group headed `## 4. [app] [e2e-test] Check the route against the live stack` with no `[acceptance]` flag
- **WHEN** the group is parsed
- **THEN** it is test-only

#### Scenario: Other groups are not

- **GIVEN** a `[unit-test]` group whose tasks are all `Test:` tasks, and an `[integration-test]` group
- **WHEN** they are parsed
- **THEN** none is test-only

### Requirement: A test-only group is built as one tests commit

In a stubbed build, for a test-only group the pipeline SHALL make one commit, `test: <group title>`, after the fixers have run and the stub check loop's static checks pass
(lint, format and types), and SHALL make no `feat:` commit for it. It SHALL NOT call an agent for the group's implementation, SHALL NOT require stubs,
and SHALL NOT demand that its tests are run red. The next group's tests SHALL be written after that commit, and after the last group the build SHALL
go on as it does after an implementation commit.

#### Scenario: A test-only last group

- **GIVEN** a stubbed build of a unit of groups 1 and 2, where group 2 is test-only
- **WHEN** it is built
- **THEN** the branch holds `test:` and `feat:` commits for group 1 and one `test:` commit for group 2, no implementation agent call was made for group 2, and the build goes on to its checks

#### Scenario: A test-only group in the middle

- **GIVEN** groups 1, 2 and 3 where group 2 is test-only
- **WHEN** the unit is built
- **THEN** the branch reads `test:`/`feat:` for group 1, `test:` for group 2, then `test:`/`feat:` for group 3, and group 3's tests are written after group 2's commit

#### Scenario: A unit of only test-only groups

- **GIVEN** a unit whose groups are all test-only
- **WHEN** it is built
- **THEN** the branch holds one `test:` commit per group and no `feat:` commit, and the unit is not stopped for lacking an implementation

#### Scenario: A failing static check

- **GIVEN** a test-only group whose tests fail the type check
- **WHEN** the stub check loop runs
- **THEN** it hands the output to the test agent, as for any group, and the tests commit is made only after the checks pass

#### Scenario: A test-only group's file is formatted before its commit

- **GIVEN** a test-only group whose tests agent leaves a file the repo's formatter would change
- **WHEN** the stub check loop runs
- **THEN** the fixers format it before the static check, the check passes without an agent call and the lone `test:` commit holds the formatted file

### Requirement: The pair count counts a test-only group by its tests commit

After the last group a stubbed build SHALL count the groups the branch satisfies: a group is satisfied by its `test:` and `feat:` pair, or, when it
is test-only, by its `test:` commit. A count short of the groups SHALL stop the unit naming the groups missing. A group that is not test-only and has
no implementation commit SHALL still stop the unit.

#### Scenario: A test-only group is counted

- **GIVEN** a stubbed build whose last group is test-only and whose `test:` commit is made
- **WHEN** the groups are counted
- **THEN** the count is full and the unit goes on to its checks

#### Scenario: An ordinary group with no implementation still fails

- **GIVEN** a group that is `[unit-test]` or `[integration-test]`, even one holding only tests, whose implementation made no commit
- **WHEN** the groups are counted
- **THEN** the unit stops with "the branch holds no tests and implementation pair for group <n> (<title>)"

### Requirement: A test-only group is done when its tests commit is on the branch

A stubbed build SHALL take the group it is on from the branch's commit subjects in the unit's order, a test-only group counting as done when its
`test:` commit is there. A killed run, a restack and a requeue SHALL resume at the first group not done, SHALL NOT write a done test-only group
again, and SHALL NOT route a test-only group to an implementation step.

#### Scenario: Resume after a kill

- **GIVEN** a unit of groups 1 (ordinary) and 2 (test-only) whose branch holds group 1's pair and group 2's `test:` commit
- **WHEN** the run is resumed
- **THEN** no group is written again and the build goes on to its checks

#### Scenario: Killed before the test-only commit

- **GIVEN** the same unit whose branch holds only group 1's pair
- **WHEN** the run is resumed
- **THEN** group 2's tests are written, not an implementation

### Requirement: The push gate accepts a lone tests commit only for a test-only group

For a stubbed build, `check_structure` and `check_branch` SHALL be given the unit's groups from the plan and SHALL accept a `test:` commit with no
`feat:` commit directly after it only when it is the commit of a test-only group. A `test:` commit of any other group SHALL still be followed
directly by a `feat:` commit with its title. A test-only commit followed by another group's `test:` commit SHALL NOT be reported as two tests
commits in a row. The rule that the branch has an implementation commit SHALL NOT apply to a unit whose groups are all test-only. With no groups
given, no group SHALL be test-only and every rule SHALL be as before.

#### Scenario: A lone test commit of a test-only group

- **GIVEN** a branch `test: A`, `feat: A`, `test: Drive the service` where the plan's last group, "Drive the service", is test-only
- **WHEN** the push gate runs
- **THEN** the structure passes

#### Scenario: A lone test commit of an ordinary group is refused

- **GIVEN** a branch `test: A`, `feat: A`, `test: B` where group B is not test-only
- **WHEN** the push gate runs
- **THEN** it is refused, saying `test: B` is not directly followed by `feat: B`

#### Scenario: A test commit followed by neither

- **GIVEN** `test: B` followed by `feat: C` where B is not test-only
- **WHEN** the push gate runs
- **THEN** it is refused naming both titles

#### Scenario: A unit of only test-only groups

- **GIVEN** a branch of `test:` commits only, one per group, every group test-only
- **WHEN** the push gate runs
- **THEN** it does not report a missing implementation commit

#### Scenario: A test-only commit before another group

- **GIVEN** `test: B` (test-only) followed by `test: C` and `feat: C`
- **WHEN** the push gate runs
- **THEN** it does not report two tests commits in a row

#### Scenario: No plan

- **GIVEN** `abk gate` run on a branch with no unit
- **WHEN** it finds a lone `test:` commit
- **THEN** it is refused as before

### Requirement: No red run is demanded at a test-only group's tests commit

At the tests commit of a test-only group the push gate SHALL run the profile's clean command (with types in a stubbed build) and SHALL NOT run the
red command or read a red result, since its live-stack tests cannot run in the builder's session. At the tests commit of every other group, including
a `unit-test` or `integration-test` group, the gate SHALL run the red command and read it as before. A result recorded for a test-only commit SHALL
be cached apart from one recorded with a red run.

#### Scenario: An e2e-only tests commit of a test-only group

- **GIVEN** a test-only group's `test:` commit holding only `local_stack` tests that collect nothing or fail on a refused connection
- **WHEN** the push gate runs
- **THEN** it is not refused for "no tests ran" or for an unrecognised failure, and its lint, format and types are still checked

#### Scenario: A unit test's tests commit still runs red

- **GIVEN** an ordinary group's `test:` commit holding unit tests that pass at that commit
- **WHEN** the push gate runs
- **THEN** it is refused for "nothing failed at the tests commit", as before

#### Scenario: Cached apart

- **GIVEN** a result cached for a commit judged without a red run
- **WHEN** the same patch is judged as an ordinary tests commit
- **THEN** the cached result is not reused
