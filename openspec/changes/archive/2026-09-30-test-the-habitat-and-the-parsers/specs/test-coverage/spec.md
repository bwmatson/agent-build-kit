# Spec Delta

## Purpose

Defines that the environment the pipeline builds in is covered by a test, that the functions reading
untrusted text are covered with realistic input, and that tests reach public surfaces.

## ADDED Requirements

### Requirement: The environment a build runs in is covered by a test

There SHALL be a test that, in a real git worktree of a repository, puts a commit through that
repository's own gate — so that a tooling or configuration change which prevents the gate running
where the pipeline runs it fails a check rather than a unit. It SHALL be marked to run where the
framework's integration tests run rather than in the default suite.

#### Scenario: A gate that cannot see the files

- **WHEN** a checker is configured so that it matches no files inside a worktree
- **THEN** the test fails, naming the checker

#### Scenario: Checks that disagree with each other

- **WHEN** the repository's linter would reject a line its formatter produces
- **THEN** the test fails rather than a unit's commit being rejected later

#### Scenario: The default suite stays hermetic

- **WHEN** the default test suite runs
- **THEN** this test is not among it

### Requirement: The functions that read untrusted text are tested with realistic input

Every function that interprets text the framework does not produce — a diff, an agent's transcript,
a provider's refusal, an agent's structured answer — SHALL have tests over input of the shape it
will actually meet, including the cases that distinguish it from a naive reading.

#### Scenario: A diff carries context

- **WHEN** a diff is read for the tests a change added
- **THEN** a test appearing only on a context line is not counted, and the test proves it

#### Scenario: A transcript that mentions a limit

- **WHEN** a successful run's transcript contains the words of a usage refusal
- **THEN** it is not classified as a refusal, and the test proves it

#### Scenario: An answer short of an entry

- **WHEN** a structured answer omits one required entry
- **THEN** the omission is reported by name, and the test proves it

### Requirement: A test reaches a public surface

A test SHALL NOT import a private name in order to exercise its logic. Where behaviour worth testing
sits in a private helper, that helper SHALL either be made part of its module's interface — named and
documented with its contract — or be exercised through the public function that uses it.

#### Scenario: Behaviour worth naming

- **WHEN** a private helper answers a question with a contract of its own
- **THEN** it becomes part of the module's interface and is tested directly

#### Scenario: Behaviour that is incidental

- **WHEN** a private helper is a detail of how a public function does its job
- **THEN** it is tested through that function, not reached into

#### Scenario: The convention is recorded

- **WHEN** a contributor reads the repository's testing conventions
- **THEN** this rule is among them
