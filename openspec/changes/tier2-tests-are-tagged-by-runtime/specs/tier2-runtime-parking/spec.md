## ADDED Requirements

### Requirement: An e2e-test run executes the groups that can run and names the ones it cannot

An e2e-test run SHALL leave the blocked runtimes out through the one selection. It SHALL find, by listing without running, which blocked runtimes hold a test the run would have executed (among the unit's own tests under own scope, among all of the marker under full scope) and SHALL report those as parked on its result. A listing that fails SHALL park the group and say why, not run it. A result with a parked runtime SHALL NOT be a complete pass: its snapshot and its status description SHALL name the parked runtime and SHALL NOT say the suite passed, and nothing SHALL post a success for it. A blocked runtime that holds no test the run would have executed SHALL park nothing. Each failed test SHALL carry its runtime group, found by listing it under each runtime's tag, and a failure whose group cannot be found SHALL be marked unknown and SHALL NOT be classified.

#### Scenario: Only the groups that can run

- **GIVEN** `acp` blocked and a repo with untagged, `claude_code` and `acp` tests
- **WHEN** a full-scope e2e-test run executes
- **THEN** it runs the untagged and `claude_code` tests, reports `acp` as parked, and its result is not a complete pass

#### Scenario: A blocked runtime with no test in the run

- **GIVEN** `acp` blocked and a unit whose own tests are all untagged
- **WHEN** its e2e-test run executes
- **THEN** it runs them, parks nothing, and is a complete pass

#### Scenario: Nothing else to run

- **GIVEN** `acp` blocked and a unit whose only own test is tagged `runtime_acp`
- **WHEN** its e2e-test run executes
- **THEN** no command runs, the stack lock is not taken, and the result parks `acp`

#### Scenario: A failure's group

- **GIVEN** a run whose failed test is tagged `runtime_claude_code`
- **WHEN** the result is read
- **THEN** the failure carries the group `claude_code`

### Requirement: A unit parks the tests it cannot run and resumes only that group when the block lifts

A unit whose e2e-test run passed the groups that ran and parked a blocked runtime SHALL be held planned with a note naming the runtime and the block's reason, the parked runtimes and the commit the run was on stored, and SHALL go on to nothing else. It SHALL NOT receive feedback, SHALL NOT count a fix round, SHALL NOT be sent for rework, SHALL NOT record a failure or write a fix change, and SHALL NOT post a status. A unit with no own test in the blocked group SHALL NOT be affected. A unit whose other groups failed SHALL fail as before and SHALL NOT be parked. A pass step SHALL resume a parked unit, once and through the delivery gated units use, when none of the runtimes it waits on is blocked, following the configuration (a runtime it allows releases the unit) and an expired deadline. The resumed unit SHALL run only the parked group on the stored commit, add the first run's result to the snapshot it posts, and post its status only when both runs passed; it SHALL park again when the group is still blocked, and SHALL run the whole selection when its head is not the stored commit. A parked unit SHALL hold no place against the unit limit, and a tick whose only work is a parked unit SHALL NOT be idle.

#### Scenario: A unit parks

- **GIVEN** a unit with one own test tagged `runtime_acp` and one untagged, with `acp` blocked
- **WHEN** it reaches e2e-test
- **THEN** the untagged test runs and passes, the unit is held planned waiting for runtime `acp`, no feedback, record, fix change or status is written, and no rework round is spent

#### Scenario: A unit with no test in the blocked group

- **GIVEN** `acp` blocked and a unit whose own tests are untagged
- **WHEN** it reaches e2e-test
- **THEN** it passes e2e-test and goes on

#### Scenario: Resume after the block lifts

- **GIVEN** a unit parked on `acp` and `abk e2e-test unblock acp` run
- **WHEN** the next pass runs
- **THEN** the unit is resumed once, runs only the `acp` tests on the stored commit, and posts its status after both runs passed

#### Scenario: Still blocked

- **GIVEN** a parked unit and its runtime still blocked
- **WHEN** a pass runs
- **THEN** the unit is left as it is

#### Scenario: The commit moved

- **GIVEN** a parked unit whose head is no longer the stored commit when it resumes
- **WHEN** its e2e-test step runs
- **THEN** it runs the whole selection, not only the parked group

#### Scenario: The ran groups fail

- **GIVEN** a unit whose untagged own test fails while its `acp` test is parked
- **WHEN** it reaches e2e-test
- **THEN** it fails as before with the output as feedback and is not parked

#### Scenario: The status shows the wait

- **GIVEN** a parked unit
- **WHEN** `abk status` runs
- **THEN** it lists the unit as waiting for runtime `acp` with the reason and the deadline, and it is not counted against the unit limit

### Requirement: Post-merge verification waits for a held split

The post-merge live check SHALL take the same selection and leave the held splits out. When a held split holds a live test among the change's files the verification SHALL deploy nothing, run nothing, record nothing, log that it was skipped for that split, be tried again the next round, and the change SHALL NOT be archived meanwhile. A held split holding no test among the change's files SHALL NOT delay it, and when the split is released the verification SHALL run and record as before.

#### Scenario: Skipped for a held split

- **GIVEN** a merged change whose files include a live test in the split `acp` and `acp` held
- **WHEN** the verification step runs
- **THEN** nothing is deployed or run, no verification is recorded, the change is not archived, and the log says it was skipped for `acp`

#### Scenario: Not affected

- **GIVEN** `acp` held and a merged change whose live tests are in no split
- **WHEN** the verification step runs
- **THEN** it runs without the `acp` tests and records as before

### Requirement: A failure and the record belong to a runtime, and a blocked runtime never records one

The record of failures that also fail on the base SHALL carry the runtime group of the failing test (`base` for an entry written before), and the fix change written for it SHALL name the runtime. A runtime that is blocked SHALL record no failure, write no fix change and hold no unit, because none of its tests runs. A failure whose runtime cannot be found SHALL be the unit's own failure, with its output as feedback, and SHALL be recorded nowhere.

#### Scenario: A runtime on the record

- **GIVEN** an `acp` test that fails on the unit and on the base while `acp` is usable
- **WHEN** the failure is recorded
- **THEN** the entry carries `acp` and the fix change's proposal names the runtime

#### Scenario: An older entry

- **GIVEN** an entry written before this change
- **WHEN** it is read
- **THEN** its runtime is `base`

#### Scenario: A blocked runtime records nothing

- **GIVEN** `acp` blocked and a unit with failing `acp` tests
- **WHEN** the unit reaches e2e-test
- **THEN** the `acp` tests do not run, nothing is recorded and no `fix-failing` change is written

#### Scenario: A failure of unknown runtime

- **GIVEN** a failed test whose runtime cannot be found
- **WHEN** the verdict is made
- **THEN** it is the unit's own failure and nothing is recorded
