## ADDED Requirements

### Requirement: An e2e-test run leaves out held splits, names the parked ones and attributes each failure to its split

An e2e-test run SHALL leave the held splits out through the one selection, SHALL find by listing, without running them, which held splits hold a test the run would have executed (among the unit's own identifiers under own scope, among all under full scope) and SHALL report those splits as parked on its result. A result with a parked split SHALL NOT be a complete pass: its snapshot and status description SHALL name the split and SHALL NOT say the suite passed. A parked split with nothing else to run SHALL run no command and take no lock, and a listing that fails SHALL park the split and say why instead of running it. Each failed test SHALL carry its split (`rest` or a declared split), found by listing the failed identifiers under each split's selector; a failure whose split cannot be found SHALL be marked `unknown` and SHALL NOT be classified. A result stored with the older `group` key SHALL read it as `split`. A run limited to one split (a resume, a scheduled one) SHALL run only that split's selection.

#### Scenario: Only the splits that can run

- **GIVEN** a unit with one own test in split `acp`, held, and one in no split
- **WHEN** it runs e2e-test
- **THEN** the second runs and passes and the result reports `acp` as parked

#### Scenario: A held split with no test in the run

- **GIVEN** `acp` held and a unit whose own tests are in no split
- **WHEN** it runs e2e-test
- **THEN** nothing is parked and the result is as without a hold

#### Scenario: Nothing else to run

- **GIVEN** a unit whose own tests are all in the held split
- **WHEN** it runs e2e-test
- **THEN** no command runs, no lock is taken, and the result names the parked split

#### Scenario: A failure's split

- **GIVEN** a failed test selected by the marker of `claude_code`
- **WHEN** the result is read
- **THEN** the failure carries the split `claude_code`, and one whose split cannot be found carries `unknown` and is the unit's own

#### Scenario: A listing that fails

- **GIVEN** a held split whose listing fails
- **WHEN** the run decides what to park
- **THEN** the split is parked and the log says its tests could not be listed

### Requirement: A unit parks the tests it cannot run and resumes only that split when it is released

A unit whose e2e-test run passed the splits that ran and parked a held split SHALL be held planned with the cause `split_held` and the note "waiting for e2e-test split <name>" naming the split and the hold's reason, with the parked splits and the commit the run was on stored, and SHALL go on to nothing else. It SHALL NOT receive feedback, count a fix round, be sent for rework, record a failure, write a fix change or post a status. A unit with no own test in the held split SHALL NOT be affected, and a unit whose other splits failed SHALL fail as before and SHALL NOT be parked. The resumed unit SHALL run only the parked split on the stored commit, add the first run's result to the snapshot it posts, and post its status only when both runs passed; it SHALL park again when the split is still held and SHALL run the whole selection when its head is not the stored commit. A unit stored before this change with the cause `runtime_blocked` and parked runtimes SHALL read as parked on those names as splits.

#### Scenario: A unit parks

- **GIVEN** a unit with one own test in the held split `acp` and one in no split
- **WHEN** it reaches e2e-test
- **THEN** the second runs, and the unit is held planned waiting for e2e-test split `acp`, with no feedback, record, fix change, status or rework round

#### Scenario: Parked on two splits

- **GIVEN** a unit with own tests in two held splits
- **WHEN** it parks
- **THEN** its note names both

#### Scenario: Resume

- **GIVEN** a unit parked on `acp` and `acp` released
- **WHEN** the unit resumes
- **THEN** it runs only the `acp` selection on the stored commit and posts its status after both runs passed

#### Scenario: The commit moved

- **GIVEN** a parked unit whose head is no longer the stored commit
- **WHEN** it resumes
- **THEN** it runs the whole selection

#### Scenario: A unit stored before

- **GIVEN** a stored unit with the cause `runtime_blocked`
- **WHEN** it is read
- **THEN** it reads as `split_held` with the same names as parked splits

### Requirement: A failure and the record belong to a split, and a held split never records one

The record of failures that also fail on the base SHALL carry the split of the failing test, and an entry written before this change SHALL read its `runtime` key as `split` and its value `base` as `rest`. The open-fix gate SHALL hold a run only for an open fix whose split the run would execute: a record of `rest` holds every run that executes `rest`, a record of a declared split holds a run that executes that split, and a run that leaves a split out (because it is held, or because it runs another split alone) SHALL NOT be held by that split's record. A held split's tests SHALL NOT run, so SHALL NOT record a failure or write a fix change. A failure whose split is unknown SHALL be the unit's own failure with the output as feedback and no record. Two failures of one test in different splits SHALL be two entries, and the written fix change SHALL name the split. The gate's other bounds (the fix change's own unit, a unit already waiting, the entry's repo) SHALL be unchanged.

#### Scenario: A split on the record

- **GIVEN** a failure of a test in `acp` on an unheld run
- **WHEN** it is recorded
- **THEN** the entry carries `acp` and the fix change names it

#### Scenario: An older entry

- **GIVEN** an entry written with `runtime: base`
- **WHEN** it is read
- **THEN** it reads as the split `rest`

#### Scenario: A split's failure holds only the runs that execute it

- **GIVEN** an open fix recorded for `acp`, and a full-scope run that leaves `acp` out because it is held, or that runs `claude_code` alone
- **WHEN** a unit reaches e2e-test
- **THEN** it runs e2e-test and gains no `Needs:` line, while a run that executes `acp` is held by the fix

#### Scenario: A held split records nothing

- **GIVEN** a held split with failing tests
- **WHEN** a unit runs e2e-test
- **THEN** the split's tests do not run, nothing is recorded and no `fix-failing` change is written

#### Scenario: An unknown split

- **GIVEN** a failure whose split cannot be found
- **WHEN** the unit's e2e-test run is judged
- **THEN** it fails the unit with the output as feedback and no record

### Requirement: The scheduled run is one change per declared split and `rest`

A due repo SHALL get one `scheduled-e2e-<repo>-<date>-<split>` change for each declared split and for `rest`, and a repo that declares no split SHALL get the `rest` change alone. The due check and the open check SHALL be per repo and split, so a split never run is due at once while the others wait out their period, and no second change SHALL be written for a (repo, split) while one is open. A change name with no split suffix, or the suffix `-base`, SHALL read as `rest`; a repo whose name begins another's, and a split whose name begins another's, SHALL NOT be confused; the date and the split SHALL be read from the name and nothing stored. A change SHALL name its split in its proposal, design and task, and SHALL pass `abk check` and `abk tags`. A held split's change SHALL be written like the others and SHALL stay open, parked, while the others run.

#### Scenario: A change per split

- **GIVEN** a due repo declaring `acp` and `claude_code`
- **WHEN** the schedule writes its changes
- **THEN** it writes `-acp`, `-claude_code` and `-rest` changes, and a repo declaring none gets only `-rest`

#### Scenario: A split never run

- **GIVEN** a repo whose other splits ran last week and a newly declared split
- **WHEN** the due check runs
- **THEN** only the new split is due

#### Scenario: One open does not stop the others

- **GIVEN** an open change for `acp`
- **WHEN** the schedule runs again
- **THEN** no second `acp` change is written and the other splits' changes are

#### Scenario: An older name

- **GIVEN** an archived change named with no suffix, and another ending `-base`
- **WHEN** the due check runs for `rest`
- **THEN** both are read as `rest` changes

#### Scenario: A held split's change

- **GIVEN** `acp` held
- **WHEN** the schedule writes and the units run
- **THEN** the `-acp` change is written and stays open while the others run
