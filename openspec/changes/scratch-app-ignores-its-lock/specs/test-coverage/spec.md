## ADDED Requirements

### Requirement: The fixture an acceptance test builds in stays clean under its own tier-1 commands

The scratch repository that acceptance tests build a unit in SHALL be such that running its tier-1 commands,
the ones its language profile produces, leaves no change for git to report in its worktree, untracked files
included. A file those commands create that the repository does not commit SHALL be ignored by the repository,
and SHALL NOT be committed to avoid a network resolution. A tier-1 test SHALL pin this, so that a fixture that
would hold a unit for an uncommitted file fails a check rather than a billed agent run.

#### Scenario: A lock created by the first run

- **GIVEN** the scratch app with a test added and committed
- **WHEN** its lint and test commands run in the worktree
- **THEN** each exits 0, the lock file exists in the worktree, and `git status --porcelain
  --untracked-files=all` lists nothing

#### Scenario: A fixture that leaves a file behind

- **GIVEN** a scratch app whose ignore rules do not cover a file its tier-1 commands create
- **WHEN** the test runs
- **THEN** it fails naming that file

#### Scenario: The default suite stays hermetic

- **WHEN** the default test suite runs
- **THEN** this test is not among it
