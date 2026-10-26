## ADDED Requirements

### Requirement: A gate added to a started unit holds it

A `Needs:` line added to a task group after its unit has started SHALL apply on the next tick
without re-planning the change. A unit that is `failed` or `held` while its gate is unmet SHALL NOT
be resumed by `abk requeue`: it SHALL become `planned` with the cause `gated`, keep its thread,
branch and saved feedback, remember the mode it was requeued with, and be resumed in that mode by
the pass once the gate clears. A unit that is running SHALL NOT be interrupted. A merge-gated
dependency SHALL NOT change the unit's base or send it back as an upstream change.

#### Scenario: A failed unit is requeued before its prerequisite merges

- **GIVEN** a failed unit with a thread, and a `Needs: <change> group <n> merged` line added to its
  group for a group that has not merged
- **WHEN** the operator runs `abk requeue` on it
- **THEN** the unit is `planned` with the cause `gated`, its thread and branch are kept, no agent
  runs, and the command names the group it waits for

#### Scenario: The prerequisite merges

- **GIVEN** that gated unit
- **WHEN** the prerequisite merges and the pass runs
- **THEN** the unit resumes at the node it stopped at, in the mode it was requeued with

#### Scenario: A running unit is not interrupted

- **GIVEN** a unit with an agent step in progress
- **WHEN** a `Needs: ... merged` line is added to its group
- **THEN** the step finishes, and the tick logs once that the unit now waits for the dependency

#### Scenario: A unit sent back for rework while gated

- **GIVEN** an in-review unit whose gate is unmet and a review comment that sends it back
- **WHEN** the pass looks for units to readmit
- **THEN** the unit is `planned` with the cause `gated`, not started, until the gate clears

#### Scenario: The dependency is not the unit's base

- **GIVEN** a unit with no stacking edge to a dependency that is in review
- **WHEN** a `merged` need on that dependency is added
- **THEN** the unit's base is unchanged and it is not sent back as an upstream change

#### Scenario: Only a Needs line changed

- **WHEN** an edit changes a `Needs:` line and nothing else in `tasks.md`
- **THEN** no planner call is made and the gate applies on the next tick

#### Scenario: The status shows the wait

- **GIVEN** a gated unit
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting on the prerequisite group, not as failed or held
