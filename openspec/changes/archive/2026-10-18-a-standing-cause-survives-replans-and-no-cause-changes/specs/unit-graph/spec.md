## MODIFIED Requirements

### Requirement: A unit with no recorded cause is simply not readmitted

A unit whose history records no cause SHALL NOT be readmitted by a running pass, and the framework
SHALL NOT log or document special handling for such units beyond listing them in the status.
A unit has no recorded cause only when its record was written before causes were kept, or when
a state change a caller recorded ended its cause. A replan, a demotion to `unplanned`, a
promotion back to `planned`, an `unplan` of a vanished change and a join SHALL NOT leave a unit
with no recorded cause that had a standing cause before the change.

#### Scenario: A unit from before causes

- **GIVEN** a planned unit whose history has no cause
- **WHEN** a running pass looks for units sent back
- **THEN** it is not readmitted and nothing is logged about it

#### Scenario: A unit a replan demoted and promoted

- **GIVEN** a planned unit with a branch whose cause is `split_held`, which a replan omitted (so it became `unplanned`) and a later replan included again
- **WHEN** the status is read
- **THEN** its cause reads `split_held` and it is not listed as having no recorded cause
