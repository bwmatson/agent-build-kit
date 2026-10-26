## ADDED Requirements

### Requirement: A planner edge never closes a cycle with stored work

After a plan is parsed and before it is stored, the pipeline SHALL check the plan's dependencies against the whole graph of units that are not
finished: every stored unit's dependencies, the plan's units, and the dependencies the `Needs:` lines of every change declare toward them. A
dependency the planner proposed that would close a cycle SHALL be dropped from the plan, the drop SHALL be logged naming the cycle, and the rest of
the plan SHALL stand. A dependency a `Needs:` line declares SHALL NOT be dropped for a planner dependency. A cycle made only of `Needs:` and stored
dependencies SHALL leave the plan standing and be reported as an error, and a replan of that change SHALL exit non-zero naming it.

#### Scenario: A planner edge back into a change that needs it

- **WHEN** a stored unit of a second change depends on the first change's group 1 through a `Needs:` line, and the plan for the first change has its unit 1 depend on that second unit
- **THEN** the dependency of unit 1 on the second unit is dropped, the log names the cycle, and unit 1 is ready

#### Scenario: A planner edge closing a cycle through another planner edge

- **WHEN** a stored unit depends, by the planner's own earlier edge, on a unit the new plan gives a dependency on it
- **THEN** the new dependency is dropped and the stored one stays

#### Scenario: A planner edge that closes no cycle

- **WHEN** a plan has a dependency on a stored unit that is not part of any cycle
- **THEN** the dependency is kept

#### Scenario: A longer cycle across three changes

- **WHEN** a plan's dependency would close a cycle through units of two other changes
- **THEN** it is dropped and the log names all three changes' units in order

#### Scenario: A diamond or a chain is not a cycle

- **WHEN** units depend on each other as a chain or as a diamond across changes
- **THEN** no dependency is dropped and nothing is reported

#### Scenario: A cycle with no planner edge in it

- **WHEN** the `Needs:` lines and the stored dependencies alone form a cycle
- **THEN** the plan stands unchanged, the cycle is reported as an error, and a replan exits non-zero

### Requirement: A `Needs:` dependency that would close a cycle is refused

When the pipeline applies a `Needs:` line as a dependency, it SHALL NOT add one that would close a cycle with the unit graph as linked so far. The
unit SHALL keep the dependencies it had, its other `Needs:` dependencies SHALL still be applied, and the log SHALL name the refused dependency and
the cycle. A dependency already stored SHALL be left alone. A replan SHALL exit non-zero when a dependency was refused, and a tick SHALL log it and
carry on.

#### Scenario: The edge closes a cycle

- **WHEN** a `Needs:` line would make a unit depend on a unit that already waits, directly or through others, on it
- **THEN** the dependency is not added, the unit keeps its dependencies, and the log names the cycle

#### Scenario: Another Needs of the same unit

- **WHEN** one of a unit's two `Needs:` lines is refused for a cycle
- **THEN** the other is still applied

#### Scenario: A replan that refused one

- **WHEN** `abk replan` links a `Needs:` and one is refused
- **THEN** it prints the cycle and exits non-zero, and a tick that links the same line logs it once and does not fail

#### Scenario: A cycle already stored

- **WHEN** the store already holds a cycle an older version wrote
- **THEN** linking removes nothing and refuses nothing, and the status reports the deadlock

### Requirement: A cycle in `Needs:` lines is an error before any planning

`abk tags` and `abk check` SHALL report a cycle formed by the `Needs:` lines of two or more changes and the order of each change's consecutive groups
(a group marked `Independent:` has no edge to the one before), naming each group in it, counting it as a problem in each change that has a `Needs:`
line on it, and exiting non-zero.

#### Scenario: Two changes that need each other

- **WHEN** group 2 of one change needs group 1 of another, which needs group 2 of the first
- **THEN** `abk tags` names the cycle under each change and exits non-zero, and `abk check` reports it too

#### Scenario: A chain or a diamond across changes

- **WHEN** the `Needs:` lines form a chain or a diamond
- **THEN** nothing is reported

#### Scenario: A Needs on the change's own group or an independent group

- **WHEN** a `Needs:` names a group of its own change, or the group is independent
- **THEN** no cycle is reported and the other messages are unchanged

### Requirement: A deadlock in the stored graph is reported

When planned units wait on each other in a cycle, `abk status` SHALL list each cycle once as `deadlocked:` followed by its units in order, the reason
a pass that starts nothing SHALL name the deadlock ahead of any other reason, and the ready-queue report SHALL give the units in it, and the units
waiting on them, that reason. A deadlock SHALL NOT be reported as a full queue or as nothing ready. It SHALL be derived from the stored dependencies
each time, so removing an edge ends it, and nothing SHALL break it automatically.

#### Scenario: Two units wait on each other

- **WHEN** two planned units depend on each other
- **THEN** the status shows one `deadlocked:` line naming both and the cycle, not one per unit

#### Scenario: Two separate cycles

- **WHEN** the graph holds two disjoint cycles
- **THEN** the status shows two lines

#### Scenario: A pass that starts nothing

- **WHEN** nothing starts because every ready candidate is in or behind a cycle
- **THEN** the log says `nothing can start: deadlocked:` and the cycle, not "queue is full" or "nothing ready to build"

#### Scenario: A unit behind the cycle

- **WHEN** a unit waits on a unit that is in a cycle
- **THEN** the ready-queue report says it waits on the deadlocked unit, and units outside the cycle start as usual

#### Scenario: The edge is removed

- **WHEN** a person replans or edits a `Needs:` line so the cycle is gone
- **THEN** the next status reports no deadlock

#### Scenario: No false report

- **WHEN** planned units form a chain or a diamond
- **THEN** no deadlock is reported

### Requirement: A replan clears a stale planner edge and leaves started units alone

A replan SHALL replace the dependencies of a unit that has not started with the plan's, so a planner dependency dropped for a cycle is gone from the
stored unit. The dependencies of a unit that has started SHALL never be changed by a plan, a dropped edge or a refused `Needs:`.

#### Scenario: A stale edge on an unstarted unit

- **WHEN** an unstarted unit stores a planner dependency that closes a cycle and its change is replanned
- **THEN** the stored unit no longer has it and its state, branch and history are unchanged

#### Scenario: A started unit

- **WHEN** a running, in-review, failed or held unit of the change has dependencies and the change is replanned
- **THEN** its dependencies are the same afterwards, and a cycle through it is reported rather than edited

### Requirement: The planner is told not to close a cycle

The planner's prompt SHALL say that a unit shown as not yet started must not be made to depend, directly or through others, on a unit of the change
being planned. This is advice; the check of a planner edge against stored work is the guarantee, and SHALL NOT depend on the planner following it.

#### Scenario: The prompt

- **WHEN** the prompt is built with an unstarted unit of another change in flight
- **THEN** it carries that rule beside the in-flight units

#### Scenario: A planner that ignores it

- **WHEN** the planner returns a dependency that closes a cycle anyway
- **THEN** the dependency is dropped as above and the plan stands
