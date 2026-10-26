## ADDED Requirements

### Requirement: How often the whole e2e-test suite runs is a setting

The setting `e2e_schedule` SHALL be `weekly`, `daily`, `monthly` or `off` and SHALL default to `weekly`. It SHALL be settable for all repos as
`limits.e2e_schedule` and for one repo as `repos.<name>.tests.e2e_schedule`; the repo's value, when set, SHALL win, and the due check, the open-change
check and `off` SHALL each be made per repo. Any other value in either place SHALL be refused when the configuration loads, naming the setting and the
four values; an unquoted `off` read as a boolean false SHALL mean `off`. `abk config --show` SHALL show the values set. With `off` for a repo the pipeline
SHALL NOT write a scheduled change for that repo, at any time; the record of pre-existing failures and the fix
changes already written SHALL work as before.

#### Scenario: The default

- **GIVEN** a configuration with no `limits.e2e_schedule`
- **WHEN** it is loaded
- **THEN** the value is `weekly`, and `abk config --show` prints it

#### Scenario: Off creates nothing

- **GIVEN** `off` in effect for a repo (set on the repo or by `limits.e2e_schedule`) and that repo with e2e-test units and no scheduled change, ever
- **WHEN** rounds run for any length of time
- **THEN** no scheduled change is written, and a recorded failure's fix change is still found and waited on as before

#### Scenario: A repo overrides the default

- **GIVEN** `limits.e2e_schedule: weekly`, one repo with `tests.e2e_schedule: off` and another with `daily`, each due
- **WHEN** a round runs
- **THEN** no change is written for the first, and one is written for the second, which is next due a day after its date

#### Scenario: A value that is not one of the four

- **GIVEN** `limits.e2e_schedule: hourly`, or `tests.e2e_schedule: hourly` on a repo
- **WHEN** the configuration is loaded
- **THEN** it is refused with a message naming `limits.e2e_schedule` and the values

### Requirement: A round writes the scheduled change when one is due

When the schedule is due for a repo that has at least one e2e-test unit and no scheduled change of that repo is open, a round SHALL write the change
`scheduled-e2e-<repo>-<date>`, with the date the day it is written, without a model: a proposal, a design, and a `tasks.md` that holds the
line `Acceptance: none` with its reason, one group `[<repo>] [e2e-test]` named for running the full e2e-test suite on the default branch, with `Priority: 3`
and a `Separate:` line, and no spec. Due SHALL be the date in the name of the repo's latest scheduled change, open or archived, plus one day for `daily`,
seven for `weekly` and thirty for `monthly`, reached or passed; with none, due at once. At most one scheduled change of a repo SHALL be open, and a
period missed SHALL be made up once. Nothing about the schedule SHALL be stored but the change names. Two overlapping ticks SHALL write one change. The
change SHALL pass `abk check` and `abk tags`. `abk tick --dry-run` SHALL say `would write: <change>` or `exists: <change>` for each repo and write
nothing.

#### Scenario: Weekly, due

- **GIVEN** `weekly` in effect and a repo whose latest scheduled change, archived, is dated eight days ago
- **WHEN** a round runs
- **THEN** the change `scheduled-e2e-<repo>-<today>` is written with its one e2e-test group, `Acceptance: none`, priority 3 and no spec

#### Scenario: Weekly, not due

- **GIVEN** `weekly` and a latest scheduled change dated three days ago
- **WHEN** a round runs
- **THEN** nothing is written

#### Scenario: One is open

- **GIVEN** a scheduled change of the repo that is open, whatever its age and whether its unit is running, failed or waiting on a fix
- **WHEN** a round runs and the schedule is past due
- **THEN** no second change is written

#### Scenario: A missed period is made up once

- **GIVEN** `weekly` and a latest scheduled change dated five weeks ago
- **WHEN** a round runs, and again after the change is written
- **THEN** one change is written, and no second one in the second round

#### Scenario: The first one

- **GIVEN** a repo with an e2e-test unit in the store and no scheduled change, open or archived
- **WHEN** a round runs
- **THEN** a change is written

#### Scenario: A repo with no e2e-test unit

- **GIVEN** one repo with e2e-test units and one without
- **WHEN** a round runs
- **THEN** one change is written, for the first

#### Scenario: Two ticks

- **GIVEN** two ticks that find a repo due at the same moment
- **WHEN** both write
- **THEN** one change exists and the second reports that it exists

#### Scenario: The dry run

- **GIVEN** a due repo
- **WHEN** `abk tick --dry-run` runs
- **THEN** it prints `would write: <change>`, nothing is written, and with the change open it prints `exists: <change>`

#### Scenario: An idle installation notices

- **GIVEN** no unit in progress and no change to plan, and a repo that is due
- **WHEN** a tick runs
- **THEN** it does not return as idle, and the change is written; with nothing due it returns as idle with no usage read

### Requirement: A scheduled unit builds nothing and runs the whole suite

A unit of a scheduled change SHALL go straight to its e2e-test step: no tests, implementation, checks or review step, no agent call by the pipeline, no
commit, no push and no pull request, whatever feedback the unit holds. It SHALL run the whole e2e-test marker of its repo whatever
`e2e_unit_scope` is, on the repo's default branch as it is when the run starts, or on the branch of the fix it waits on once released.

#### Scenario: The unit starts at e2e-test

- **GIVEN** a planned unit of a scheduled change
- **WHEN** it starts
- **THEN** its first step is e2e-test, no agent is called, and no branch is pushed

#### Scenario: Own scope does not narrow it

- **GIVEN** `own` in effect for the repo and a scheduled unit
- **WHEN** its e2e-test step runs
- **THEN** the whole marker runs

#### Scenario: Left-over feedback

- **GIVEN** a scheduled unit that failed and holds saved feedback, and is requeued
- **WHEN** it starts
- **THEN** it runs e2e-test again and does not enter a rework step

### Requirement: A passing scheduled run finishes the unit and the change

When the whole marker passes, a scheduled unit SHALL end satisfied with a note that names the counts and the commit, with no pull request, its tasks
ticked, and the change SHALL archive through the existing archive path.

#### Scenario: A pass

- **GIVEN** a scheduled unit whose run passes
- **WHEN** the step ends
- **THEN** the unit is satisfied with the note `scheduled e2e-test passed: <n> passed, <m> skipped on <sha>`, no pull request exists, and the change is archived by a later round

#### Scenario: The next schedule reads the archive

- **GIVEN** the archived change
- **WHEN** the next due date is computed
- **THEN** it is the date in the change's name plus the period

### Requirement: A failing scheduled run is recorded, fixed once and waited on

A test a scheduled run names as failed SHALL be a pre-existing failure by definition, because its tree is its base: no run on the base SHALL be made for it.
Each such test SHALL be recorded and given one fix change, and the unit SHALL be parked on those changes, through the same functions as any unit, and
SHALL run the whole marker again when released through the normal resume path. With `limits.e2e_base_runs` at zero, or a failure with no test id to
read, the unit SHALL fail as any unit's e2e-test failure does and nothing SHALL be recorded.

#### Scenario: A failing test

- **GIVEN** a scheduled run in which one test fails
- **WHEN** the step ends
- **THEN** no base run is made, the test is recorded, one `fix-failing-*` change exists for it, the unit's group has a `Needs:` line on it, and the unit is planned, gated, with a resume requeue

#### Scenario: A test already being fixed

- **GIVEN** a fix change for the test that is open
- **WHEN** a scheduled run fails in that test
- **THEN** no second change is written, the step reports `exists: <change>`, and the unit waits on the existing one

#### Scenario: Released after the fix

- **GIVEN** a parked scheduled unit whose fix change's unit is now in review or merged
- **WHEN** the pass runs
- **THEN** the unit resumes at e2e-test and runs the whole marker again, and a pass ends it as above

#### Scenario: The base run is off

- **GIVEN** `limits.e2e_base_runs: 0`
- **WHEN** a scheduled run fails
- **THEN** the unit fails with the output as feedback and nothing is recorded or written

#### Scenario: A failure with no readable test

- **GIVEN** a scheduled run that fails with no test id in its output
- **WHEN** the step ends
- **THEN** the unit fails with the output as feedback and nothing is recorded

### Requirement: A scheduled unit is tracked as normal work

A scheduled unit SHALL appear in `abk status` with its state and what it waits on, SHALL count against `limits.max_units_in_progress`, SHALL take the e2e-test
lock and wait for it as `tier2-lock-wait-holds-the-unit` says, and SHALL be started only when the usage guard lets a unit start. A scheduled change
SHALL be planned only when the guard lets a model call be made. No scheduled unit SHALL start while another e2e-test run holds the lock; it SHALL wait as any
unit does.

#### Scenario: Shown

- **GIVEN** a planned scheduled unit
- **WHEN** `abk status` is read
- **THEN** it is listed like any unit, with its change name and its state

#### Scenario: The unit limit

- **GIVEN** `limits.max_units_in_progress` units already in progress
- **WHEN** a scheduled unit is ready
- **THEN** it does not start until a place is free

#### Scenario: The lock is held

- **GIVEN** another unit holding the e2e-test lock
- **WHEN** a scheduled unit's e2e-test step starts
- **THEN** it waits for the lock without failing and runs when it is free

#### Scenario: The usage guard refuses

- **GIVEN** a usage window the guard refuses
- **WHEN** a scheduled change is due and rounds run
- **THEN** the change may be written, it is not planned and its unit does not start until the guard admits it, and no second change is written
