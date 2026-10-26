## MODIFIED Requirements

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
