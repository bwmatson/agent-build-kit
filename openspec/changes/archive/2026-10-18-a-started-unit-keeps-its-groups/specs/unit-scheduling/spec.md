## MODIFIED Requirements

### Requirement: A replan leaves started work alone and says what changed

A replan SHALL NOT change a unit that is running, in review, failed, held, merged or satisfied: its state, branch, pull request, feedback and history
SHALL stay. A planned unit SHALL take the new plan's shape, an unstarted planned unit the plan no longer contains SHALL become `unplanned`, and a join
the plan proposed SHALL be dropped when a unit started meanwhile. A planned unit that has started (it has a branch, a pushed commit, a pull request or an
approval) and that the plan no longer contains SHALL NOT become `unplanned`: it SHALL stay as it is, and the replan SHALL print that it was kept, that it has
work and is not in the plan, and the `abk retire` line that ends it. The command SHALL print only what differs from the store before the replan:
dependencies added and removed, estimate and tier changes, units that became `unplanned`, joins dropped, and each started unit it
left alone. It SHALL print nothing for a unit that did not change.

#### Scenario: Started and finished units are kept

- **GIVEN** units that are running, in review, failed, held, merged and satisfied
- **WHEN** their change is planned again
- **THEN** each keeps its state, branch, pull request and history, and each started one is reported as kept

#### Scenario: A stale dependency is removed

- **GIVEN** a planned unit that depends on a unit the new plan does not ask for, and a dependency that a `Needs:` line asks for
- **WHEN** its change is planned again
- **THEN** the first dependency is gone, the second remains, and the output says which was removed

#### Scenario: A unit the plan dropped

- **GIVEN** an unstarted planned unit that the new plan does not contain
- **WHEN** its change is planned again
- **THEN** it becomes `unplanned` and is reported

#### Scenario: A join dropped

- **GIVEN** a plan that proposes a join with a unit that started while the planner ran
- **WHEN** the plan is applied
- **THEN** the join is dropped and reported

#### Scenario: Nothing changed

- **GIVEN** a change whose new plan equals the stored one
- **WHEN** it is planned again
- **THEN** the command prints that nothing changed

#### Scenario: A planned unit with work that the plan omits is kept

- **GIVEN** a planned unit with a branch, parked on a held tier 2 split, that the new plan does not contain
- **WHEN** its change is planned again
- **THEN** it stays `planned` with its branch and history, it does not become `unplanned`, and the output says `kept: <unit> has work; not in the plan` and gives `abk retire <unit>` with a reason
