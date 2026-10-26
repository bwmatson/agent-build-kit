## MODIFIED Requirements

### Requirement: A unit records its actual size beside its estimate

A unit with a pull request SHALL record the pull request's actual changed lines, excluding
generated files, when the pull request is opened and again whenever a push updates it, and
SHALL log and list in the status when the actual size exceeds the ceiling. The graph page
SHALL NOT mark a unit for its size. The ceiling SHALL NOT block a unit from landing.

#### Scenario: A unit lands over the ceiling

- **GIVEN** a unit estimated at 600 lines whose pull request changes 1,400
- **WHEN** the pull request is opened
- **THEN** the unit records 1,400 beside its estimate, its log and the status say it is over
  the ceiling, and the graph page shows its node as it shows one under the ceiling

#### Scenario: A rework changes the size

- **WHEN** a push after a rework changes the pull request's size
- **THEN** the recorded actual size is updated

#### Scenario: A lockfile

- **WHEN** a pull request includes a lockfile's changes
- **THEN** they are not counted in the actual size
