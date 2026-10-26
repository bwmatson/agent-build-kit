# local-forge Specification

## Purpose
TBD - created by archiving change local-forge. Update Purpose after archive.

## Requirements

### Requirement: A repo can use a forge that keeps pull requests locally

A repo SHALL be able to set its forge to `local`. Its pull requests, review notes, replies and
decisions SHALL be kept in a file in the state directory, and labels, drafts, statuses, checks and
stacks SHALL do nothing. The forge SHALL NOT be inferred from a remote.

#### Scenario: Opening a pull request

- **GIVEN** a repo whose forge is `local`
- **WHEN** a unit's branch is pushed and its pull request opened
- **THEN** the pull request is recorded in the state directory with a number, its head and base, and
  no network call is made

#### Scenario: Operations with no local meaning

- **WHEN** a label, a draft flag, a status or a check rerun is asked of the forge
- **THEN** it is accepted and nothing changes

### Requirement: A local pull request is merged when git says so

A local pull request SHALL be reported merged when its branch tip is contained in the trunk, or when
its change is found in the trunk by patch identity. Nothing in the pipeline or the UI SHALL perform
the merge.

#### Scenario: A person merges

- **GIVEN** a unit in review
- **WHEN** a person merges its branch into the trunk with git
- **THEN** the next poll reports the pull request merged and the unit moves on as for a host's merge

#### Scenario: A squash

- **GIVEN** a trunk containing the change as one squashed commit
- **WHEN** the pull request is listed
- **THEN** it is reported merged

#### Scenario: Approve is not a merge

- **WHEN** a reviewer approves in the UI
- **THEN** the approval is recorded and the pull request stays open

### Requirement: A repo without a remote is built against its own trunk

For a repo with no remote, pushing, fetching and the base comparison SHALL use the repo's own trunk
and local branches, and the requirement that only the approved commit is pushed SHALL still hold.

#### Scenario: A unit with no remote

- **GIVEN** a repo with no `origin`
- **WHEN** a unit is built and approved
- **THEN** its branch is the local pull request's head, the base is the local trunk, and the approved
  commit is the branch tip

### Requirement: An agent can read its local pull request

The forge SHALL declare read-only `abk pr view` and `abk pr diff` as the commands its agents may run,
and neither SHALL be among its denied commands.

#### Scenario: An agent reads

- **WHEN** an agent runs `abk pr view` for its unit
- **THEN** it prints the local pull request, and no state changes
