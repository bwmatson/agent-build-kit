## MODIFIED Requirements

### Requirement: A task group may carry a priority

A task group SHALL be able to carry a priority, an integer from 0 to 5 with 0 the most urgent (the emergency lane) and 5 the least, written as a `Priority:` line. A
line inside a group SHALL set that group's priority, and a line above the first group SHALL set the default for the change's
groups, which a group's own line overrides. A group with neither SHALL have priority 3. A value that is not an integer from 0 to
5 SHALL be reported with its line number and a message that names the range 0 to 5, and the task-tag listing SHALL show a group's priority when it is not 3, and, when a group
that depends on it (as the planner chains the groups, or by a `Needs:` line) is more urgent, the priority it will be promoted to
and the group that causes it. A change that has no such line SHALL be read as before.

#### Scenario: A group sets its own priority

- **GIVEN** a group with the line `Priority: 2`
- **WHEN** the change is read
- **THEN** the group's priority is 2

#### Scenario: A group may be priority 0

- **GIVEN** a group with the line `Priority: 0`
- **WHEN** the change is read
- **THEN** the group's priority is 0 and it is not read as having none

#### Scenario: A change default

- **GIVEN** a `Priority: 4` line above the first group and one group with `Priority: 2`
- **WHEN** the change is read
- **THEN** that group's priority is 2 and the others' is 4

#### Scenario: A change default of 0

- **GIVEN** a `Priority: 0` line above the first group and one group with `Priority: 2`
- **WHEN** the change is read
- **THEN** that group's priority is 2 and the others' is 0

#### Scenario: No line

- **WHEN** a group has no priority line and the change has no default
- **THEN** its priority is 3

#### Scenario: A value outside the scale

- **GIVEN** a `Priority:` line of `6`, `-1`, `high` or `2.5`
- **WHEN** the change's tags are checked
- **THEN** the line is reported with its number and a message naming 0 to 5, and the change is not accepted

#### Scenario: A change that existed before priority 0

- **GIVEN** a `tasks.md` whose priority lines are all from 1 to 5, or absent
- **WHEN** it is read
- **THEN** every group has the priority it had before

#### Scenario: The listing shows a promotion

- **GIVEN** group 5 at priority 3 that group 9 at priority 1 depends on through the chain
- **WHEN** `abk tags` lists the change
- **THEN** group 5 reads `(priority 3, promoted to 1 by group 9)` and a group nothing more urgent depends on reads as before

#### Scenario: The listing shows a promotion to 0

- **GIVEN** group 5 at priority 1 that group 9 at priority 0 depends on through the chain
- **WHEN** `abk tags` lists the change
- **THEN** group 5 reads `(priority 1, promoted to 0 by group 9)`, and group 9 reads `(priority 0)`

### Requirement: A unit has the priority of its most urgent group

A unit SHALL have the most urgent (smallest) priority among the groups it builds, including groups carried from other changes, and a priority of 0 SHALL count as a priority, never as none. A
unit that has not started SHALL be promoted to the priority of the most urgent unit that waits on it, as the requirement on promotion
says. A unit's effective priority SHALL be the most urgent priority among the unit and every unit that waits on it, directly or through a
chain of dependencies in any repository, not counting merged, closed or satisfied units or units the round excludes (those named
out by `--only`, held by a lease or in a backoff). A started unit SHALL keep the priority it started with, a promoted one included, when the
file changes, and a unit that has not started SHALL take the file's value when its change is next planned, and then be promoted again
if units still wait on it. A stored unit with no priority SHALL read as 3, and a stored priority of 0 SHALL read back as 0.

#### Scenario: A unit of several groups

- **GIVEN** a unit built from a group of priority 4 and a group of priority 2
- **WHEN** its priority is read
- **THEN** it is 2

#### Scenario: A unit with a priority-0 group

- **GIVEN** a unit built from a group of priority 0 and a group of priority 3
- **WHEN** its priority is read
- **THEN** it is 0

#### Scenario: A prerequisite takes the priority of what waits on it

- **GIVEN** a priority-3 unit that a priority-1 unit waits on, directly or through a chain
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 1

#### Scenario: A prerequisite of a priority-0 unit

- **GIVEN** a priority-3 unit that a priority-0 unit waits on, directly or through a chain
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 0

#### Scenario: Waiting units that are less urgent

- **GIVEN** a priority-3 unit that only priority-5 units wait on
- **WHEN** the effective priority is worked out
- **THEN** it is 3

#### Scenario: A waiter in another repository

- **GIVEN** a unit that a more urgent unit in another repository waits on
- **WHEN** the effective priority is worked out
- **THEN** it takes the waiter's priority, as a waiter in its own repository would give it

#### Scenario: A satisfied unit in the chain

- **GIVEN** a priority-1 unit that waits on a ready prerequisite through a unit that was satisfied
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite's is 1

#### Scenario: A unit left out of the round gives no priority

- **GIVEN** a priority-1 unit that waits on a ready prerequisite and is left out of the round by a lease, a backoff or `--only`
- **WHEN** the effective priority is worked out
- **THEN** the prerequisite does not take priority 1

#### Scenario: A started unit keeps its priority

- **GIVEN** a unit that has started, and its group's priority line is then edited
- **WHEN** the change is next planned
- **THEN** the unit keeps the priority it had, and a unit of the same change that has not started takes the new one

#### Scenario: A record from before priorities

- **WHEN** a stored unit has no priority
- **THEN** it reads as 3

#### Scenario: A stored priority 0 is kept

- **GIVEN** a unit of priority 0 written to the store
- **WHEN** the store is read again
- **THEN** its priority is 0, not the default 3

#### Scenario: A started unit keeps a promotion

- **GIVEN** a unit promoted from 3 to 1 by a waiter that then starts
- **WHEN** the waiter is merged and the change is replanned
- **THEN** the started unit still has priority 1 and still names the waiter it was promoted from

#### Scenario: A started unit keeps a promotion to 0

- **GIVEN** a unit promoted from 3 to 0 by a priority-0 waiter that then starts
- **WHEN** the waiter is merged and the change is replanned
- **THEN** the started unit still has priority 0, not 3, and still names the waiter it was promoted from

## ADDED Requirements

### Requirement: The planner is shown priorities and the rule for edges between them

The planner's prompt SHALL mark each group heading of the change with its priority, from the group's own line, else the change's default, else
3, and SHALL list each unit already in flight with its stored priority. It SHALL state that a unit depends on another only for code the other
introduces, that a more urgent unit is not made to depend on a less urgent one merely because their groups are adjacent in the tasks, that
independent groups are not chained, and that a unit takes the most urgent priority of the groups it builds. The prompt SHALL be advice; the
check in the next requirement is the guarantee.

#### Scenario: Group headings carry priorities

- **GIVEN** groups with `Priority: 1`, no line, and a change default of 4 with one group at 2
- **WHEN** the prompt is built
- **THEN** the headings read `(priority 1)`, `(priority 3)`, `(priority 4)` and `(priority 2)`, beside any project or built-by mark

#### Scenario: In-flight units carry priorities

- **GIVEN** a started unit of priority 2 and an unstarted unit promoted to 1
- **WHEN** the prompt is built
- **THEN** the lines show `priority 2` and `priority 1`

#### Scenario: The rule is stated

- **WHEN** the prompt is built
- **THEN** it says to depend on a unit only for code it introduces and not to chain adjacent or independent groups

### Requirement: A plan does not make a unit wait on a less urgent unit that has not started without giving a reason

A unit object of the planner's reply SHALL be able to carry `needs_less_urgent`, an object whose keys are ids the unit lists in `depends_on`
and whose values are non-blank strings that say why. A plan that is not an object of that shape SHALL be refused naming the unit. A plan SHALL be
refused when a unit depends on a unit of the plan, or a stored unit, that has not started and whose own priority (the most urgent of its groups'
priorities, not its stored value) is less urgent than the dependent's, and the dependent gives no reason for that edge. The refusal SHALL name
the unit, the edge, both priorities, and say to drop the edge or give the reason, in its first line, and name any further edge after it. An edge
to a unit that has started, or is merged, closed or satisfied, an edge to an equal or more urgent unit and an edge with a reason SHALL NOT be refused.
The refusal SHALL be a planning failure like any other: the attempt is recorded with the reason and the unit ids, the change is planned again by
the next tick within the allowed attempts, the listing of `abk replan` reads `failing n/m: <reason>` and then `given up`, and `abk replan` exits
non-zero when the change did not plan. No raw error SHALL reach the person. The next attempt's prompt SHALL carry the previous attempt's refusal
reason when the recorded plan is for the current `tasks.md`, and SHALL carry nothing after an outage, a failed call or an edit of `tasks.md`.

#### Scenario: An avoidable edge is refused

- **GIVEN** a plan in which the unit for a priority-1 group depends on the unit for a priority-3 group, with no reason
- **WHEN** the plan is checked
- **THEN** it is refused with a first line naming the unit, `app/1`, priorities 1 and 3, and the two ways out

#### Scenario: An edge with a reason is accepted

- **GIVEN** the same plan with `needs_less_urgent` giving a reason for the edge
- **WHEN** the plan is checked
- **THEN** it passes

#### Scenario: Equal and more urgent targets

- **GIVEN** a unit that depends on units of the same or of a more urgent priority
- **WHEN** the plan is checked
- **THEN** it passes

#### Scenario: A started or finished target

- **GIVEN** a priority-1 unit that depends on a stored priority-5 unit that has started, or is merged
- **WHEN** the plan is checked
- **THEN** it passes

#### Scenario: A stored promotion does not hide the edge

- **GIVEN** a stored unstarted unit promoted to 1 whose own groups are priority 3, and a priority-1 unit that depends on it without a reason
- **WHEN** the plan is checked
- **THEN** it is refused

#### Scenario: A malformed reason

- **GIVEN** a `needs_less_urgent` that is not an object, names a unit that is not in `depends_on` or has a blank reason
- **WHEN** the plan is read
- **THEN** it is refused naming the unit

#### Scenario: A refusal is retried and fed back

- **GIVEN** a change whose first plan was refused for an avoidable edge
- **WHEN** the next tick plans it
- **THEN** the prompt ends with the previous refusal reason, and the attempt count is 2

#### Scenario: A change that never satisfies the check

- **GIVEN** 3 allowed attempts and a model that returns the avoidable edge each time
- **WHEN** the change is planned three times
- **THEN** the listing reads `failing 1/3`, `failing 2/3`, then `given up` with the reason, and `abk replan` exits 1

#### Scenario: A priority-1 unit depends on a priority-0 unit

- **GIVEN** a plan in which the unit for a priority-1 group depends on the unit for a priority-0 group that has not started, with no reason
- **WHEN** the plan is checked
- **THEN** it passes, since 0 is more urgent than 1

#### Scenario: A priority-0 unit depends on a less urgent unit

- **GIVEN** a plan in which the unit for a priority-0 group depends on the unit for a priority-1 group (or a priority-3 group) that has not started, with no reason
- **WHEN** the plan is checked
- **THEN** it is refused with a first line naming the unit, `(priority 0)`, the dependency and `(priority 1)` (or 3), and the two ways out

### Requirement: A unit that has not started is promoted to the urgency of the units that wait on it

After a plan and after the `Needs:` lines are linked, each unit that has not started SHALL be given the most urgent of its own priority (from
its groups) and the priorities of every unit that waits on it, directly or through a chain, in any repository, leaving out units that are
`unplanned` or finished and looking through a satisfied one. A started waiter counts with its stored priority and an unstarted one with its own.
When the result is more urgent than the unit's own, the unit SHALL record the waiter that gives it in `promoted_from` (of equally urgent waiters,
the id that sorts first), and otherwise `promoted_from` SHALL be empty. Both SHALL be recomputed at every such pass, so a promotion lapses at the
next pass after the waiter is merged, closed, dropped or loses its edge, and a replan SHALL never leave a unit below what its waiters need. A unit
that has started SHALL NOT be changed: it keeps its priority and its `promoted_from`. `promoted_from` SHALL be left out of the stored record when
empty, and a record without it SHALL read as empty. Setting the priority of an unstarted unit from its groups SHALL clear it.

#### Scenario: A reasoned edge promotes its target

- **GIVEN** an unstarted priority-3 unit that an unstarted priority-1 unit depends on with a reason
- **WHEN** the plan is made
- **THEN** the prerequisite's priority is 1 and `promoted_from` names the dependent

#### Scenario: A declared need promotes every tick

- **GIVEN** a `Needs:` line from a priority-1 group to a stored unstarted priority-3 unit
- **WHEN** the tick links the needs
- **THEN** the unit is promoted to 1 and names the dependent

#### Scenario: Through a chain

- **GIVEN** units A, B and C of priority 5, 3 and 1, each depending on the one before
- **WHEN** promotion runs
- **THEN** A and B are 1 and both name C or the waiter that gives it, and C is unchanged

#### Scenario: A started ancestor keeps its priority

- **GIVEN** a started priority-3 unit that an unstarted priority-1 unit waits on
- **WHEN** promotion runs
- **THEN** its priority and `promoted_from` are unchanged, and its effective priority is 1

#### Scenario: The promotion lapses

- **GIVEN** a promoted unit whose waiter is merged or dropped
- **WHEN** the next tick or replan runs
- **THEN** the unit has the priority of its groups and an empty `promoted_from`

#### Scenario: A replan does not lower it

- **GIVEN** a promoted unit whose change is replanned and the unit planned again with the default priority
- **WHEN** the replan finishes
- **THEN** the unit is promoted again to what its waiters need

#### Scenario: Equal and less urgent waiters

- **GIVEN** a priority-2 unit that only priority-2 and priority-4 units wait on
- **WHEN** promotion runs
- **THEN** it is unchanged and `promoted_from` is empty

#### Scenario: A record without the field

- **WHEN** a stored unit has no `promoted_from`
- **THEN** it reads as empty, and an empty one is left out when written

#### Scenario: A priority-0 waiter promotes a priority-1 or priority-3 prerequisite

- **GIVEN** an unstarted priority-1 unit and an unstarted priority-3 unit that an unstarted priority-0 unit depends on with a reason
- **WHEN** promotion runs
- **THEN** both prerequisites have priority 0, and `promoted_from` names the priority-0 unit on each

#### Scenario: A promotion to 0 is stored and read back

- **GIVEN** a unit promoted to 0
- **WHEN** the store is written and read again
- **THEN** its priority is 0 and its `promoted_from` is the waiter, not empty and not the default 3

#### Scenario: A priority-1 waiter does not promote a priority-0 unit

- **GIVEN** an unstarted priority-0 unit that only a priority-1 unit waits on
- **WHEN** promotion runs
- **THEN** it is unchanged and `promoted_from` is empty

### Requirement: Authoring warns of a group less urgent than a group that depends on it

`abk tags` and `abk check` SHALL warn, and SHALL NOT fail, for each group that is less urgent than a group that depends on it directly, using the
chain the planner draws between a change's groups (an `Independent:` group has no earlier parent and is skipped as the parent of the next, and an
`[acceptance]` or `[narrow]` group depends on every earlier group) and the `Needs:` lines, whose target is read from the other change's tasks. The
warning SHALL give both groups and priorities, say the earlier group will be promoted, and say to give it the dependent's priority or lower
the dependent's. A target that cannot be read SHALL produce no warning and no error. The exit status of both commands SHALL be as it would be
without the warning.

#### Scenario: A less urgent group in the chain

- **GIVEN** group 5 at priority 3 and group 9 at priority 1 that depends on it
- **WHEN** `abk tags` or `abk check` runs
- **THEN** it prints `group 5 (priority 3) is needed by group 9 (priority 1): it will be promoted to 1; give it Priority 1 or lower group 9` and its exit status is unchanged

#### Scenario: An independent group is skipped

- **GIVEN** an `Independent:` group at priority 1 after a group at priority 3
- **WHEN** the change is checked
- **THEN** there is no warning for that pair, and the group after it is compared with the group before it

#### Scenario: An acceptance group

- **GIVEN** an `[acceptance]` group at priority 1 and earlier groups at 3
- **WHEN** the change is checked
- **THEN** each earlier group is named

#### Scenario: A needed group of another change

- **GIVEN** a `Needs:` line from a priority-1 group to a priority-3 group of another change
- **WHEN** the change is checked
- **THEN** a warning names that change and group

#### Scenario: Nothing inverted

- **GIVEN** groups whose dependents are all at least as urgent
- **WHEN** the change is checked
- **THEN** no priority warning is printed

#### Scenario: A group needed by a priority-0 group

- **GIVEN** group 5 at priority 1 and group 9 at priority 0 that depends on it
- **WHEN** `abk tags` or `abk check` runs
- **THEN** it prints `group 5 (priority 1) is needed by group 9 (priority 0): it will be promoted to 0; give it Priority 0 or lower group 9`, and its exit status is unchanged

#### Scenario: A priority-0 group needed by a less urgent group

- **GIVEN** group 5 at priority 0 and group 9 at priority 1 that depends on it
- **WHEN** the change is checked
- **THEN** no priority warning is printed

### Requirement: The graph, the status and the listing show the effective priority and where it comes from

The graph label, the ready queue of `abk status` and the priority line a tick logs SHALL show a unit's effective priority and its source: a
promoted unit as `priority N, promoted from <unit>`, a started unit that a more urgent waiter covers as `priority N, from <unit>`, a unit with a
priority that is not 3 and no source as `priority N`, and a unit at 3 with no source with nothing. The text of the status SHALL be as it was
for the cases it already named.

#### Scenario: The ready queue

- **GIVEN** an unstarted unit promoted to 1 by `app/9`
- **WHEN** `abk status` lists the ready queue
- **THEN** its line reads `priority 1, promoted from app/9`

#### Scenario: A covered started unit

- **GIVEN** a started priority-3 unit that a priority-1 unit waits on
- **WHEN** `abk status` lists the ready queue
- **THEN** its line reads `priority 1, from` that unit

#### Scenario: The graph

- **GIVEN** a promoted unit
- **WHEN** the graph is drawn
- **THEN** its label shows the effective priority and `promoted from` its source

#### Scenario: A priority-0 unit is shown

- **GIVEN** an unstarted unit of priority 0 with no source, and an unstarted priority-3 unit promoted to 0 by `app/9`
- **WHEN** `abk status` lists the ready queue and the graph is drawn
- **THEN** the first reads `priority 0`, the second `priority 0, promoted from app/9`, and neither is read as a unit at the default priority

### Requirement: The planner chooses joins by logical grouping first and priority second

The planner's prompt SHALL tell the planner to choose joins by logical grouping first: to join work that belongs together, that is groups of one
change, or groups or unstarted units of different changes that modify the same or closely related files or modules, and not to join unrelated work
merely because both are small. It SHALL tell the planner that priority is a secondary influence only: among candidates that fit equally well, the
more urgent work is joined first, so that a less urgent item does not take a partner that a more urgent item with similar files could use, and a
priority never overrides a better logical fit and never joins unrelated work. A unit made by a join SHALL keep taking the most urgent priority of
all its groups, so the joined work is an efficiency gain and the unit resolves the most urgent item at that item's priority. This SHALL be guidance
in the prompt only: no check on priority is added, there is no equal-priority requirement and no limit on the gap between priorities, and the
validity checks of `check_joins` SHALL be unchanged.

#### Scenario: Groups of one change that touch the same module are joined before a group of another change

- **GIVEN** two small groups of one change that modify the same module and a small group of another change that modifies a related one
- **WHEN** the prompt is built
- **THEN** its joining paragraph says to join work that belongs together first, groups of one change and groups that touch the same or closely
  related files or modules, and that unrelated work is not joined merely because both are small

#### Scenario: The more urgent work is offered a partner first among equal fits

- **GIVEN** a more urgent unit and a less urgent unit with similar files that would compete for one join partner
- **WHEN** the prompt is built
- **THEN** its joining paragraph says that among equally good fits the more urgent work is joined first and that a less urgent item does not take a
  partner a more urgent one with similar files could use (decided on the prompt text, as the planner's reply is not scripted)

#### Scenario: A priority never joins unrelated work

- **WHEN** the prompt is built
- **THEN** its joining paragraph says that a priority never overrides a better logical fit and never joins unrelated work, and states no priority
  number limit

#### Scenario: The joined unit keeps the most urgent priority

- **GIVEN** a join of a group of priority 1 and a group of priority 4
- **WHEN** the unit's priority is read
- **THEN** it is 1, and the prompt says that a unit takes the most urgent priority of its groups

#### Scenario: The join checks are unchanged

- **GIVEN** a join of two units of different priorities that satisfies every existing rule, and one that breaks a rule
- **WHEN** `check_joins` runs
- **THEN** the first is accepted and the second is refused for that rule alone, and no rule reads a priority

### Requirement: A change to the planner's rules does not replan recorded plans

A recorded plan is keyed by the hash of its change's `tasks.md`, so a change of the planner's prompt, schema or checks SHALL NOT make a recorded
plan stale, and the tick SHALL NOT replan one for it. The promotion of units that have not started SHALL apply to the edges already stored at the
first pass after the change, without a replan. A person SHALL plan a change again with `abk replan <change>` to drop an avoidable edge, and that
SHALL replace only the edges of units that have not started and keep every started unit.

#### Scenario: Nothing is replanned by the build

- **GIVEN** a change planned before the rule and a `tasks.md` that has not changed
- **WHEN** a tick runs
- **THEN** the change is not planned again

#### Scenario: Stored edges are promoted at once

- **GIVEN** a stored edge from an unstarted priority-1 unit to an unstarted priority-3 unit
- **WHEN** the first tick after the rule runs
- **THEN** the prerequisite is promoted to 1

#### Scenario: A replan drops an avoidable edge

- **GIVEN** that change and a model that no longer draws the edge
- **WHEN** `abk replan <change>` runs
- **THEN** the dependent has no such edge, the prerequisite returns to 3, and started units are unchanged
