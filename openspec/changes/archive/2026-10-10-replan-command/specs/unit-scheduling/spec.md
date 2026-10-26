## ADDED Requirements

### Requirement: A person can plan a change again on demand

`abk replan` SHALL plan the changes it is given, or selects with `--all` or `--failed`, now, whatever the recorded hash says: it SHALL remove each
selected change's recorded plan, run the planner for those changes only, and link the `Needs:` lines as a tick does. A unit id SHALL be accepted
and mapped to its change. With no selector it SHALL list each change with the state of its plan and plan nothing. `--forget` SHALL remove the
records, make no planner call, and leave the planning to the next tick. It SHALL refuse a name that is not a change, a change without a
`tasks.md` and a change whose task groups have tag errors, and plan nothing for them. Its exit status SHALL be 0 when every selected change
planned, 1 when any failed or was refused, and 2 for a usage error. A tick SHALL be unchanged: it SHALL plan a change only when its `tasks.md`
differs from the recorded plan or its last plan did not succeed and attempts remain.

#### Scenario: A change is planned although its plan is recorded

- **GIVEN** a change whose recorded plan matches its `tasks.md`
- **WHEN** `abk replan` is run with its name
- **THEN** the planner is asked for it, and its record is written with the new hash, no failed attempts and success

#### Scenario: A unit id names its change

- **WHEN** `abk replan` is given the id of a unit
- **THEN** the change that carries it is planned, and the command says which change that is

#### Scenario: A change that gave up

- **GIVEN** a change that stopped being planned after its failed attempts
- **WHEN** `abk replan --failed` is run
- **THEN** it is planned, and its failed attempts start over

#### Scenario: Every change

- **WHEN** `abk replan --all` is run
- **THEN** every active change is planned

#### Scenario: Forget only

- **WHEN** `abk replan --forget` is run with a name
- **THEN** its record is removed, the planner is not asked, and the next tick plans it

#### Scenario: No selector

- **WHEN** `abk replan` is run with no name and no selector
- **THEN** it lists each change with the state of its plan, plans nothing and exits with the usage status

#### Scenario: A change that cannot be planned

- **WHEN** the name is not a change, the change has no `tasks.md`, or its task groups have tag errors
- **THEN** the command says why, plans nothing for it, and exits with status 1

#### Scenario: A tick skips an unchanged change

- **GIVEN** a change whose recorded plan matches its `tasks.md` and succeeded
- **WHEN** a tick plans
- **THEN** the planner is not asked

### Requirement: A replan leaves started work alone and says what changed

A replan SHALL NOT change a unit that is running, in review, failed, held, merged or satisfied: its state, branch, pull request, feedback and history
SHALL stay. A planned unit SHALL take the new plan's shape, an unstarted planned unit the plan no longer contains SHALL become `unplanned`, and a join
the plan proposed SHALL be dropped when a unit started meanwhile. The command SHALL print only what differs from the store before the replan:
dependencies and merge gates added and removed, estimate and tier changes, units that became `unplanned`, joins dropped, and each started unit it
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

### Requirement: The recorded plans are written safely

The file of recorded plans SHALL be read, changed and written under a lock and written atomically, so a command run beside a pass that is planning
does not lose an update.

#### Scenario: Two writers

- **GIVEN** two writers changing different changes' records at once
- **WHEN** both finish
- **THEN** both records are present

### Requirement: A failing plan names the way out

The message that a change is not planned until its `tasks.md` changes, and the status line for a failing plan, SHALL also say to run `abk replan`.

#### Scenario: A change gives up

- **WHEN** a change reaches its allowed failed attempts
- **THEN** the message names `abk replan` as well as an edit of `tasks.md`
