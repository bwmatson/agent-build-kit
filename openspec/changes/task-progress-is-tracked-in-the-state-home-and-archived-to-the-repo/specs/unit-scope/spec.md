## MODIFIED Requirements

### Requirement: A unit whose groups are already implemented is satisfied, not failed

When a unit's step produces nothing and the unit has added no commits of its own while the
repository's tier-1 checks pass at its tip, the unit SHALL end in a state recording that
its work arrived by another route: its task groups SHALL be ticked in the change's tracking copy, its dependents SHALL
stop waiting for it, it SHALL NOT be given a pull request, and it SHALL NOT appear among
failed units. This SHALL be judged from the branch and the checks, never from the run's
own account of itself.

#### Scenario: A predecessor did the work

- **WHEN** a unit finds its groups already implemented, has no commits of its own, and the
  checks pass
- **THEN** it is recorded as satisfied, its groups are ticked in the tracking copy, and no pull request is
  opened

#### Scenario: Nothing committed and the checks fail

- **WHEN** a unit has no commits of its own and the checks do not pass
- **THEN** it is a failure, as it is today

#### Scenario: Partly done

- **WHEN** a unit has commits of its own and finds the remainder already implemented
- **THEN** it goes to review as usual, because it has a diff to review
