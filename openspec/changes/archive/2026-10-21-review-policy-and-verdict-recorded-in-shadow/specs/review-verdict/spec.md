## ADDED Requirements

### Requirement: A deterministic verdict decides a unit's review tier

For each unit abk SHALL compute a verdict by a function that calls no model and gives the same answer for the same recorded facts. The
verdict SHALL be the highest of these floors: the planner's estimate when there is one; `full` when a changed path is protected;
`full` when a group the unit builds is flagged `contract`, `narrow` or `acceptance`; `full` when a recorded gate result is missing or
failed (red-first, unit-test and, for a unit of the e2e-test kind, e2e-test), a gate that has not yet run because it runs after
review being pending, which is met in an interim verdict and missing in a final one; `full` when the reviewer has an open required finding;
the reviewer's classification, and `full` when it is missing; and `light` when the unit's class has fewer than `min_samples` units with
a recorded outcome or a clean-merge rate below `min_clean_rate`. A unit of the `integration-test` kind SHALL be treated as a `unit-test` unit for every floor, taking none from the e2e-test gate. A floor SHALL only raise the tier. The verdict SHALL name the rule
that decided it.

#### Scenario: A protected path

- **GIVEN** a unit with every gate green, classified `auto`, that changed a protected path
- **WHEN** the verdict is computed
- **THEN** it is `full` and the reason names the path

#### Scenario: A missing gate

- **GIVEN** a unit with no recorded red-first result
- **WHEN** the verdict is computed
- **THEN** it is `full` and the reason says the gate has no result

#### Scenario: A class with no history

- **GIVEN** a unit with every gate green, no flag, no protected path and classification `auto`, in a class with no recorded outcomes
- **WHEN** the verdict is computed
- **THEN** the evidence tier is `auto`, the tier is `light`, and the reason says the class has too few samples

#### Scenario: The reviewer cannot lower it

- **GIVEN** a unit the planner estimated `full`
- **WHEN** the reviewer classifies it `auto`
- **THEN** the verdict is `full`

#### Scenario: The same facts, the same answer

- **WHEN** the verdict is computed twice from the same facts
- **THEN** both results are equal

### Requirement: A verdict is computed and recorded after every review round

After each review round's reply is weighed, whether it approves the unit, asks for another round or holds the unit for a person, and
when review is enabled, abk SHALL compute the verdict from the facts recorded at that moment and SHALL record it in
`runs/verdicts.json`, replacing the unit's earlier entry. The entry SHALL hold the unit id and change, the round, whether it is
**final**, its class, the planned estimate or none, the classification and drivers, the evidence tier, the tier and the reason, the
paths changed, the number of changed lines, and `brief`, whether the pull request carried the review brief, false until the change
that adds the brief says otherwise. An entry SHALL be final only when the round approved the unit; every other entry SHALL be
interim. The record SHALL be rewritten atomically and SHALL be listed with the other state files. A gate that runs after review and
has not yet run when the round ends, such as the e2e-test before the push, SHALL be **pending**: pending SHALL count as met in an
interim verdict and as a missing result in a final one.

#### Scenario: A round that asks for rework

- **WHEN** a review round asks the builder for changes
- **THEN** an interim entry is written for the unit with the round number and `final` false

#### Scenario: The approval

- **WHEN** a later round approves the unit
- **THEN** the unit's entry is replaced by a final one for that round, and the file holds one entry for the unit

#### Scenario: A pending gate

- **GIVEN** a unit of the e2e-test kind whose e2e-test has not yet run, with every other floor met
- **WHEN** an interim verdict is computed and then the final one is computed before the e2e-test has run
- **THEN** the interim verdict has no floor from the e2e-test and the final verdict is `full` saying the gate has no result

#### Scenario: A unit held for a person

- **WHEN** a round holds the unit for a person
- **THEN** its entry is interim, and no final entry exists until a later round approves it

### Requirement: The verdict changes nothing the pipeline does

No part of the pipeline SHALL read a recorded verdict to decide a state, a hold, a label, a notification, a merge or a size. A failure to
compute or write a verdict SHALL be logged and SHALL NOT fail, hold or delay the unit.

#### Scenario: The write fails

- **GIVEN** the state directory refuses the write
- **WHEN** a review round ends
- **THEN** the failure is logged and the unit goes on as it would have

### Requirement: Verdicts are counted

abk SHALL record a count of verdicts by tier, planned estimate and class, and the planner-accuracy reading, and SHALL list both in the
metric catalogue.

#### Scenario: A verdict

- **WHEN** a verdict is recorded
- **THEN** the counter increases by one with the unit's tier, estimate and class as attributes, and no unit id
