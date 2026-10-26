## MODIFIED Requirements

### Requirement: A workspace bounds how many units are in progress

The workspace SHALL configure, once under `project_limits`, the greatest number of
units in progress at once in one project, defaulting to 5, and the limit SHALL apply to
each project separately: units in progress are counted for each project (a repo's
project, see the requirement that a unit has one project), no total is kept across
projects or repos, and a repo with one project counts as that one project. A unit SHALL be in
progress from the moment it first starts until it merges, is closed or is
satisfied, whatever state it is in meanwhile — running, in review, being
reworked, paused or held part-way, or failed — and whether or not it has a pull
request. A unit that has never started, including one waiting on a dependency,
SHALL NOT count. A started unit that is blocked (a planned unit waiting on another unit) SHALL NOT
count while it is blocked, and counts again from the moment it is not. A failed unit that waits on
another unit (the units it waits on are those that stop a unit starting: a dependency not yet merged or
reviewed, or a predecessor being reworked, failed or held) SHALL NOT count while it waits, SHALL count again from the moment
the wait ends, and SHALL stay failed throughout: it is never requeued by the pipeline.

#### Scenario: Started work without a pull request

- **WHEN** a unit is paused part-way through its build and has no pull request
- **THEN** it counts as in progress

#### Scenario: A failed unit

- **WHEN** a unit has failed and waits on no other unit (a failed unit that does wait is the next scenario)
- **THEN** it counts as in progress until it is requeued and finishes, or is
  closed

#### Scenario: A failed unit waiting on a prerequisite

- **WHEN** a unit has failed and waits on a prerequisite that has not merged, or on a predecessor that is being reworked, failed or held
- **THEN** it does not count, it is still failed, and it counts again, still failed and not requeued, when the wait ends

#### Scenario: Blocked new work

- **WHEN** a unit has never started and is waiting on a dependency
- **THEN** it does not count

#### Scenario: A blocked unit that has work

- **WHEN** a unit has a branch and a run log, is planned, and is waiting on a prerequisite that has not merged
- **THEN** it does not count, and counts again when the prerequisite has merged

#### Scenario: Two projects of one repo count apart

- **GIVEN** a repo with two projects and a limit of 5, five units in progress in one of them and two in the other
- **WHEN** the count is worked out
- **THEN** the first project is at its limit with five, the second has two, and neither count includes the other's units

#### Scenario: A repo with one project

- **GIVEN** a repo that declares one project, or none
- **WHEN** the count is worked out
- **THEN** its units are counted as one project, as the repo's units were counted before projects existed

#### Scenario: Another repo's units are not counted

- **GIVEN** a limit of 5, five units in progress in one repo and one in another
- **WHEN** the count is worked out
- **THEN** each repo's count is its own, and no figure of six is kept

### Requirement: At the limit, no new unit starts

While the number of units in progress in a project is at or above the limit, the
pipeline SHALL NOT start a unit of that project that has never started, and SHALL NOT
hold back a unit of any other project on account of it. Units waiting to start SHALL
stay as they are, to be started when that project's count falls.

#### Scenario: The limit is reached

- **WHEN** five units are in progress under the default limit and a unit that
  has never started is otherwise ready
- **THEN** it does not start, and remains planned

#### Scenario: A unit finishes

- **WHEN** a unit in progress merges and the count falls below the limit
- **THEN** a waiting unit may start under the other rules

#### Scenario: A full project does not stop another

- **GIVEN** one project at its limit and a unit that has never started, otherwise ready, in each of that project and another
- **WHEN** units are chosen
- **THEN** the other project's unit starts and the full project's stays planned

#### Scenario: A full project's ready units are skipped, not the pass

- **GIVEN** the units that are ready in start order are two of a full project and then one of another
- **WHEN** units are chosen with a free build slot
- **THEN** the full project's two are skipped and the third starts

### Requirement: Holding at the limit is reported as such

When new work is held because a project's limit is reached, the tick's log and the
pipeline's status SHALL say so with one line for each full project, giving the project, the count, the limit, and
the units holding the places by state, rather than reporting that nothing is ready, and SHALL say how many blocked units of
that project are not counted and what each waits on. A failed unit that waits on another unit SHALL NOT be listed among the units holding the places, and the report SHALL say how many
of them are not counted. The line SHALL name the project when the workspace has more than one project, and SHALL read as it did before projects existed when it has one.

#### Scenario: A failed unit holding a place

- **WHEN** nothing new starts because the limit is reached and one of the units
  in progress has failed
- **THEN** the report lists that unit as failed among those holding the places

#### Scenario: Blocked units are listed

- **WHEN** the queue is full and two started units are blocked
- **THEN** the report says two blocked units are not counted and lists each with what it waits on

#### Scenario: A failed unit that waits is not listed as holding a place

- **WHEN** the queue is full and one failed unit waits on a prerequisite
- **THEN** the report does not count it or list it among the units holding the places, and says one failed unit waiting is not counted

#### Scenario: One line for each full project

- **GIVEN** a limit of 9 and two projects at it, `app/web` with seven failed and two running units and the other with nine in review
- **WHEN** the status is printed
- **THEN** it holds one queue line for each, `queue is full: app/web: 9 units in progress, limit 9 (7 failed, 2 running)` and the other's own, and no line for a project below its limit

#### Scenario: A workspace with one project

- **GIVEN** a workspace whose only repo has one project, at its limit
- **WHEN** the status is printed
- **THEN** the line reads `queue is full: 5 units in progress, limit 5 (...)`, with no project named

#### Scenario: Nothing started because a project is full

- **GIVEN** a pass that starts nothing because the only ready units belong to a full project
- **WHEN** its reason is printed
- **THEN** it holds that project's queue line and says no new unit of it starts until one finishes or is closed, and it does not name a project that holds no ready unit back

### Requirement: The running pass samples its slots

Each time a running pass refreshes, it SHALL append one `sample` row to the ledger with the counts of units running, in review, blocked and queued, the free workers, the limit and the cap, each a total over the projects that have a unit not yet finished and kept for reporting only (the limits themselves apply to each project and are never compared with a total), and SHALL set gauges for free slots and for idle slots with ready work, with no unit or change attribute. A reader that does not know the row kind SHALL skip it.

#### Scenario: One refresh

- **WHEN** a pass refreshes
- **THEN** exactly one sample row is written with those counts

#### Scenario: An unknown kind

- **WHEN** the report reads a ledger holding sample rows
- **THEN** its figures are unchanged

#### Scenario: Two live projects

- **GIVEN** two projects with unfinished units, a limit of 5 and a cap of 4
- **WHEN** a pass refreshes
- **THEN** the sample row's limit is 10, its cap is 8 and its free workers are the sum of each project's free workers

### Requirement: A tag change under a started unit is reported and not applied

When a started unit's stored repo, project, tier or flag differs from the tags of the groups it carries, the pipeline SHALL report the unit, the difference
and the way out (`abk requeue --restart` on the unit, or restoring the tag), SHALL NOT change the unit, and SHALL NOT record the plan as done, so the
report repeats until it is resolved. Renumbering or deleting a group a started unit carries SHALL be refused as before.

#### Scenario: A tier changed on a failed unit's group

- **GIVEN** a failed unit and its group, which is then re-tagged with another tier
- **WHEN** the change is planned
- **THEN** the unit and the difference are reported with the way out, the unit is unchanged and the plan is not recorded as done

#### Scenario: The report ends

- **GIVEN** a reported tag change
- **WHEN** the tag is restored, or the unit is requeued with `--restart` and takes the new tags
- **THEN** the next planning records the plan and reports nothing

#### Scenario: A started group renumbered or deleted

- **GIVEN** a group a started unit carries
- **WHEN** it is renumbered or deleted and the change is planned
- **THEN** the plan is refused with the existing message and no planner call is made

#### Scenario: A project changed on a failed unit's group

- **GIVEN** a failed unit built for the root project and its group, which is then tagged for another project
- **WHEN** the change is planned
- **THEN** the unit and the difference are reported with the way out, the unit is unchanged and the plan is not recorded as done
