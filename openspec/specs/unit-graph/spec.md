# unit-graph Specification

## Purpose
TBD - created by archiving change remove-cutover-compatibility. Update Purpose after archive.

## Requirements

### Requirement: Nothing carries a unit from the old engine

The framework SHALL NOT contain code that converts a unit from the old engine onto a thread, and
the unit store SHALL NOT accept the old engine's fields. A units store that carries any of them
SHALL fail to load with an error naming the unit and the field and telling the operator to finish
or requeue the old work first.

#### Scenario: A store with an old field

- **GIVEN** a units store in which a unit has the old engine's `review_rounds`
- **WHEN** the store is loaded
- **THEN** loading fails naming the unit and the field

#### Scenario: A tick

- **WHEN** a tick runs
- **THEN** it performs no conversion and logs none

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

### Requirement: An agent node records that its run has started

Each node that runs an agent SHALL record its own name in the unit's thread state before its agent
starts, independently of whether the runtime reports a session, and SHALL clear it when the node
completes, so that a killed run leaves it behind.

#### Scenario: A kill before the agent reports a session

- **GIVEN** a node killed after it started but before its agent named a session
- **WHEN** the thread is inspected
- **THEN** the node's name is still recorded

#### Scenario: A node that completes

- **WHEN** a node completes
- **THEN** its record is cleared

### Requirement: A node killed during an agent run resumes over the work its agent left

When a node that runs an agent is re-run after its run was killed, meaning its recorded start
names it and no live process holds the unit's branch, uncommitted changes in the unit's
worktree SHALL be taken as that node's own and SHALL NOT make the resume fail. When the node
continues its recorded session, the agent SHALL be given nothing beyond the interruption prompt.
When the node starts a new session over such changes, its prompt SHALL name the changed paths and
say they are uncommitted work from an interrupted run of the same step, to be reviewed, kept where
right, and finished, and SHALL NOT tell the agent to discard them. The node's own commit SHALL
include them, and no separate work-in-progress commit SHALL be made.

#### Scenario: A killed rework with a recorded session

- **GIVEN** a rework killed mid-edit, leaving an uncommitted file, with its session recorded
- **WHEN** the thread is resumed and the session continues
- **THEN** the unit goes on to review and the file is in the rework's commit
- **AND** the agent was given no list of leftovers

#### Scenario: A killed implement with no session

- **GIVEN** an implement node killed before its session was recorded, leaving uncommitted code
- **WHEN** it is resumed in a new session
- **THEN** its prompt names the changed paths and calls them uncommitted work from an interrupted run
- **AND** the file is still in the worktree

#### Scenario: A session that cannot be resumed

- **GIVEN** a recorded session the runtime cannot continue
- **WHEN** the node falls back to a new session
- **THEN** the prompt carries the leftover note

#### Scenario: Killed by a limit or a timeout

- **WHEN** a rate limit or a timeout kills an agent mid-run
- **THEN** the resume behaves the same way

### Requirement: Uncommitted work that is not a node's own parks the unit

When the worktree has uncommitted changes and no recorded start names the node being run, or a live
process holds the unit's branch, the unit SHALL be held with the cause `dirty_worktree`, the changed paths and a request that
a person commit or remove them, SHALL NOT be failed, and nothing SHALL be cleaned automatically. A
requeue after the tree is clean SHALL resume it, and the status SHALL list such units with their
reason.

#### Scenario: A hand edit

- **GIVEN** a unit that was not killed and whose worktree a person edited
- **WHEN** a node asks for the worktree
- **THEN** the unit is held with the paths and the request, not failed

#### Scenario: A non-agent node

- **GIVEN** a dirty tree at a node that does not run an agent
- **WHEN** it is resumed
- **THEN** the unit is held, not failed

#### Scenario: An agent node reached but never started

- **GIVEN** a unit waiting at an agent node for the usage window, with a person's edit in its tree
- **WHEN** the node is next run
- **THEN** the unit is held, because no start was recorded

#### Scenario: A runtime that reports no session

- **GIVEN** a node killed mid-edit on a runtime that names no session
- **WHEN** it is resumed
- **THEN** it resumes over the leftovers in a new session, because its start was recorded

#### Scenario: After the tree is cleaned

- **WHEN** a person cleans the tree and requeues the unit
- **THEN** it resumes at the node

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
