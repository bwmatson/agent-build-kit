## ADDED Requirements

### Requirement: The planner is shown the units that can affect a plan

The units listed to the planner as already in flight SHALL be every unit of the change being planned, and every unit of another change that is not merged or satisfied. Merged and satisfied units of other changes SHALL be replaced by one line giving their count, and that line SHALL be absent when there are none. A group of the change being planned built by a started unit SHALL still be marked as built. A plan that depends on a merged or satisfied unit SHALL still pass the plan check, and a `Needs:` line SHALL still produce its edge.

#### Scenario: Landed units of other changes are summarised

- **GIVEN** the store holds four merged or satisfied units of other changes, a failed unit and a planned unit of other changes, and two merged units of the change being planned
- **WHEN** the prompt is built
- **THEN** it lists the failed unit, the planned unit and the two merged units of this change, and one line saying four merged or satisfied units of other changes are omitted

#### Scenario: Nothing to omit

- **GIVEN** no merged or satisfied unit of another change
- **WHEN** the prompt is built
- **THEN** no summary line appears

#### Scenario: A dependency on an omitted unit

- **GIVEN** a plan that depends on a merged unit the prompt did not list
- **WHEN** the plan is checked
- **THEN** it passes

### Requirement: A planner prompt over the safe size fails as a planning failure that names its parts

A planner prompt over the safe size of the runtime's transport SHALL fail the attempt with a planner error whose first line names the change, the size and the limit, and whose following lines give the size of the template, the change's `tasks.md`, the relationships, the calibration section and the in-flight list. It SHALL be recorded as a planning failure with that first line as its reason, counted as an attempt, and retried as other planning failures are: `abk replan` plans it again, and after the allowed attempts it is given up until `tasks.md` changes or `abk replan` is run. No other retry SHALL be added.

#### Scenario: A planner prompt that is too large

- **GIVEN** a planner prompt of 2,000,001 bytes
- **WHEN** the change is planned
- **THEN** no process starts, the plan record holds an attempt and a reason naming the change, the size and the limit, `abk replan` lists it as `failing 1/3: <reason>`, and the sizes of the five parts are printed

#### Scenario: A large prompt that fits

- **GIVEN** a planner prompt of 300,000 bytes on the `stdin` transport
- **WHEN** the change is planned
- **THEN** the whole prompt is delivered and the reply is parsed into a plan

#### Scenario: Repeated failures give up as others do

- **GIVEN** a change whose prompt is too large and 3 allowed attempts
- **WHEN** it is planned three times
- **THEN** the listing reads `failing 1/3`, `failing 2/3`, then `given up`, and `abk replan --failed` plans it again
