## ADDED Requirements

### Requirement: A unit stores only its direct dependencies

A unit's stored dependencies SHALL be its direct dependencies: the transitive reduction of its dependencies over the stored graph. A dependency that
another dependency of the same unit reaches through stored dependencies, directly or through any number of units of any state and in any repository,
SHALL NOT be stored. A unit with two dependencies neither of which reaches the other SHALL keep both. Planning (`upsert`), a `Needs:` link, the
repointing of a join and every other write of a unit's dependencies SHALL store the reduced list in the order given. One function, `direct_dependencies`,
SHALL compute it, and no other code SHALL reduce a list of its own. A stored cycle SHALL NOT make the function loop or drop a dependency of the cycle.

#### Scenario: A chain with a redundant ancestor

- **GIVEN** unit B depending on A, and a plan that makes unit C depend on both B and A
- **WHEN** the plan is stored
- **THEN** C stores B alone

#### Scenario: A diamond keeps both parents

- **GIVEN** units B and C that each depend on A, and a unit D that depends on B, C and A
- **WHEN** D's dependencies are stored
- **THEN** D stores B and C, and not A

#### Scenario: Unrelated dependencies are all kept

- **GIVEN** a unit that depends on two units, neither of which reaches the other
- **WHEN** its dependencies are stored
- **THEN** it stores both, in the order given

#### Scenario: Through a merged unit and across repositories

- **GIVEN** A in one repository, B in another that depends on A, B merged, and C that depends on both
- **WHEN** C's dependencies are stored
- **THEN** C stores B alone

#### Scenario: A stored cycle

- **GIVEN** two units that depend on each other
- **WHEN** their dependencies are reduced
- **THEN** the call returns, and both dependencies are kept, because each is reached only through the other

#### Scenario: One function

- **WHEN** the writers of a unit's dependencies and the views that show them are read
- **THEN** each calls `direct_dependencies`, and none holds a reduction of its own

### Requirement: The existing store is reduced once, through the store's own methods

The first tick or `abk replan` after this change is built SHALL read the stored units and, for each unit that stores a dependency another of its
dependencies reaches, record the reduced list through `set_dependencies`, logging the unit and the dependencies removed. It SHALL NOT edit the store
file by any other route. A second tick or replan SHALL change nothing. It SHALL run only once an acceptance or narrow unit's wait is computed at run
time, so no unit loses a wait it had, and it SHALL NOT change a unit's state, branch, pull request or history other than its dependencies.

#### Scenario: A store with redundant edges

- **GIVEN** a store in which a unit stores four dependencies, three of them reached by the fourth
- **WHEN** a tick runs
- **THEN** the unit stores the fourth alone, the log names the three removed, and nothing else of the record changed

#### Scenario: Run again

- **GIVEN** a store that has been reduced
- **WHEN** a second tick or a replan runs
- **THEN** no write is made and nothing is logged for it

#### Scenario: A started unit

- **GIVEN** a running unit that stores a redundant dependency
- **WHEN** the reduction runs
- **THEN** its list is reduced, its state and branch are untouched, and its base is the one it had

### Requirement: An acceptance or narrow unit waits for every earlier unit of its change at run time

A unit whose flag is `acceptance` or `narrow` SHALL wait for every earlier unit of its own change, computed from the change's units each time and not
from stored dependencies. For each earlier unit, in the unit's repository the wait SHALL hold until it is in review, merged or satisfied, and in another
repository until it has merged or been satisfied with its work landed, exactly as a dependency on it would; a unit the plan dropped SHALL NOT hold it.
The same earlier units SHALL stop a running build of the unit when one of them goes back, and SHALL send the unit back from review while one of them
is changing its branch, as the unit's stored parents do. The rule SHALL add waits only: it SHALL NOT change the unit's base, its depth or the open
parents it waits for. A unit whose record has no flag SHALL follow the chain as any other unit does.

#### Scenario: An earlier unit sent back while its successor is in review

- **GIVEN** an acceptance unit whose stored dependency is the last unit of a chain, that last unit in review, and a unit two places before it that is sent back
  for rework
- **WHEN** the scheduler works out what is ready
- **THEN** the acceptance unit is not ready and waits for the unit sent back

#### Scenario: A running acceptance unit stops

- **GIVEN** a running acceptance unit and an earlier unit of its change, not among its stored dependencies, that goes back to planned
- **WHEN** the build checks its upstream
- **THEN** it stops with the cause upstream went back, naming that unit

#### Scenario: An acceptance unit in review follows

- **GIVEN** an acceptance unit in review and an earlier unit whose branch is changing
- **WHEN** the pass follows predecessors
- **THEN** the acceptance unit is set back to planned with that unit named

#### Scenario: An independent unit counts as an earlier unit

- **GIVEN** a change of a chain of two units, an independent unit and an acceptance unit that stores the second unit and the independent unit
- **WHEN** the scheduler works out what is ready while the independent unit is not yet in review
- **THEN** the acceptance unit waits for it and for the chain's units, the same as with every edge stored

#### Scenario: The live store

- **GIVEN** the acceptance units of a recorded store, reduced
- **WHEN** their waits are worked out
- **THEN** each waits for the same units as with the unreduced list

#### Scenario: A unit with no flag follows the chain

- **GIVEN** a unit that depends on a unit in review, whose own parent is sent back, and that has no flag
- **WHEN** the scheduler works out what is ready
- **THEN** it is ready, as a plain chain's unit is

#### Scenario: The base is untouched

- **GIVEN** an acceptance unit that waits for an earlier unit that is in review and not among its stored dependencies
- **WHEN** its base is worked out
- **THEN** it is the base the stored dependencies give

### Requirement: Every other unit follows the chain

A unit that is not an acceptance or narrow unit SHALL NOT wait for, stop for or be sent back by a unit it reaches only through another dependency. A
unit sent back for rework SHALL reach the units built on it through the chain: each parent restacks onto the reworked branch, and each unit in review
follows its predecessor. A parent whose restack is deferred or conflicted, and a thread that declines the move, SHALL leave the units behind it as they
are, as for a plain chain today.

#### Scenario: A grandparent sent back

- **GIVEN** units A, B and C in a chain, B and C in review, and A sent back for rework
- **WHEN** the passes run
- **THEN** B is set back to planned as its predecessor changes, and C follows B, with no wait of C on A

#### Scenario: A grandparent closed

- **GIVEN** a chain A, B, C with A closed and B and C in review
- **WHEN** the scheduler works out what is ready
- **THEN** C is not held by A

#### Scenario: A deferred restack

- **GIVEN** the chain with B's restack deferred
- **WHEN** the passes run
- **THEN** C is not moved ahead of B, and the gap is the one a plain chain has

#### Scenario: A merge restacks once

- **GIVEN** A merging with B and C stacked on it in a chain
- **WHEN** A's children are released
- **THEN** B is moved onto the trunk, and C, which sat on B's branch, is not moved a second time off A

#### Scenario: A branch is removed when its dependents are done

- **GIVEN** a merged unit with one direct dependent and a unit built on that dependent
- **WHEN** its branch is considered for removal
- **THEN** only the direct dependent is probed and the branch stays while it is held or not moved

### Requirement: A started unit's base does not depend on the order of its dependencies

A unit that has started SHALL build on the open parent an unstarted unit would: the unrelated open parent with the greatest stack depth, a tie going to
the later in plan order, and the same unit SHALL be the predecessor a thread is told it moves onto. Neither SHALL depend on the order the unit's
dependencies are listed in, and a dependency added later SHALL NOT change either.

#### Scenario: A later-added ancestor

- **GIVEN** a running unit that depends on B, with B built on A, and a `Needs:` line that adds A after B
- **WHEN** the base and the predecessor are worked out
- **THEN** both are B, as before the line

#### Scenario: The list is reordered

- **GIVEN** a started unit whose dependencies list A and B, B built on A
- **WHEN** the list is stored as B then A and as A then B
- **THEN** the base and the predecessor are B in both

#### Scenario: An unstarted unit

- **WHEN** the base of a unit that has not started is worked out
- **THEN** it is what it was

### Requirement: The planner is asked for the units a group exercises

The planner's instructions SHALL ask that an `[acceptance]` or `[narrow]` group's unit name the units it exercises, or removes the old half of, and SHALL
NOT ask that it depend on every unit; the instructions for an independent group SHALL say that the unit still waits for the independent unit. A plan
that does not reach every such unit SHALL be refused as before. `plan_units` SHALL give such a unit the units it exercises: the tail of its chain and
every independent unit, and not every earlier unit. A unit the planner is shown as in flight SHALL list its direct dependencies.

#### Scenario: The prompt

- **WHEN** the planner's instructions are built
- **THEN** the acceptance rule names the units exercised and does not say every unit, and the independent rule still says the unit waits for the independent one

#### Scenario: An acceptance unit after independent groups

- **GIVEN** a chain of three units, an independent unit and an acceptance group
- **WHEN** the groups are made into units
- **THEN** the acceptance unit depends on the third unit and the independent unit, and on no other

#### Scenario: A plan that misses a unit

- **GIVEN** an acceptance unit that reaches neither a unit it exercises nor anything that builds on it
- **WHEN** the plan is checked
- **THEN** it is refused naming the unit, as before

#### Scenario: In-flight lines

- **GIVEN** a stored unit that lists a redundant ancestor
- **WHEN** the planner is shown it
- **THEN** its line names its direct dependencies

### Requirement: Every view shows a unit's direct dependencies

The graph page, the Dependencies list of a unit's page, the waiting lines of `abk status`, the "Merge ... first" list of a pull request's body and the
lines a replan prints about a unit's dependencies SHALL all be made from `direct_dependencies`, so they SHALL name the same dependencies for the same
unit. The graph page SHALL draw a merged or satisfied parent only when an edge to it is kept, and SHALL draw no edge for a `Needs:` the chain implies.
A body SHALL name the unmerged direct parents, and a parent's own body names what it waits for.

#### Scenario: The same edges in every view

- **GIVEN** a chain A, B, C with C's stored list still holding A
- **WHEN** the graph, the unit's page, `abk status` and C's pull request body are made
- **THEN** each names B and none names A

#### Scenario: A merged parent

- **GIVEN** a unit that depends on a merged unit only through another dependency
- **WHEN** the graph is drawn
- **THEN** the merged unit is not drawn for it, and one that a kept edge reaches is drawn

#### Scenario: A replan line

- **GIVEN** a replan after which a unit's stored dependencies differ
- **WHEN** it prints what changed
- **THEN** it names the changes in the direct dependencies

#### Scenario: A thick edge is kept

- **GIVEN** a `Needs:` that is a direct dependency of the unit
- **WHEN** the graph is drawn
- **THEN** its edge is thick and labelled `needs`

### Requirement: A Needs line the chain implies is recorded and not linked

The stored `needs` of a unit SHALL name every unit its `Needs:` lines name, kept apart from its dependencies, and SHALL change only when the lines
do. A target the unit already reaches through its dependencies SHALL NOT be added as a dependency, now or on a later tick; a target it does not reach
SHALL be added and the dependencies stored reduced. A target that would close a cycle SHALL be refused as before, judged by reachability.

#### Scenario: Linked once

- **GIVEN** a unit that depends on a unit that already depends on the unit its `Needs:` names
- **WHEN** ten ticks run
- **THEN** the unit's dependencies never gain that unit, no line says it is now depending on it, and its `needs` names the target

#### Scenario: A target that reaches a listed dependency

- **GIVEN** a unit that depends on A and a `Needs:` that names B, which depends on A
- **WHEN** the line is linked
- **THEN** the unit stores B alone, and `needs` names B

#### Scenario: A line removed

- **WHEN** a `Needs:` line is removed
- **THEN** the unit's `needs` no longer names it on the next tick

#### Scenario: A cycle is refused

- **GIVEN** a `Needs:` line that names a unit that depends on the unit itself, directly or through others
- **WHEN** it is linked
- **THEN** it is refused as before, with the cycle logged once

## MODIFIED Requirements

### Requirement: A task group may declare itself independent of the groups before it

A task group SHALL be able to declare, with a reason, that it does not depend on
any earlier group of its change. The unit built from such a group SHALL have no
dependency on the unit before it and SHALL be ready when its change is planned,
subject to its own `Needs` lines. The group following it SHALL depend on the
last unit before the independent group. A `[narrow]` or `[acceptance]` group
SHALL wait for every earlier unit of the change, independent or not, and SHALL
store only its direct dependencies, those that no other dependency of it reaches. An
independent group SHALL NOT be joined into another unit, and no group SHALL be
joined into its unit. A change with no such declaration SHALL be planned as
before.

#### Scenario: A platform group beside application groups

- **GIVEN** a change of two groups in one repo and a third, declared independent,
  in another
- **WHEN** the change is planned
- **THEN** the third group's unit depends on nothing
- **AND** the second group's unit depends on the first, not on the third

#### Scenario: An acceptance group after an independent group

- **GIVEN** an acceptance group that follows an independent group
- **WHEN** the change is planned
- **THEN** the acceptance unit depends on the independent group's unit as well, and waits for it until it is in review

#### Scenario: No declaration

- **WHEN** a change without an independence declaration is planned
- **THEN** its units are linked as they were before this requirement

### Requirement: A Needs line starts the dependent on the parent's branch

A `Needs: <change> group <n>` line SHALL add a dependency of the unit on the unit that holds that group, and
nothing more, unless the unit already reaches that unit through its dependencies, in which case no dependency
is added and the line is applied by the one that reaches it. A same-repo dependency SHALL release its dependent once it is through its build and review loop
(in review, merged or satisfied), and the dependent SHALL start on that dependency's branch, as for any
same-repo dependency. A dependency in another repository SHALL release its dependent only once it has merged,
or been satisfied with its work landed, because a stack cannot span repositories. A dependency that is planned,
running, reworked, failed or held SHALL keep its dependent from starting. A `Needs:` line SHALL be applied on
the next tick without re-planning the change.

#### Scenario: A same-repo parent in review

- **WHEN** a unit needs a same-repo unit and that unit is in review
- **THEN** the dependent may start, on the parent's branch

#### Scenario: A parent still building

- **WHEN** a unit needs a same-repo unit that is planned, running, failed or held
- **THEN** the dependent does not start

#### Scenario: A parent that goes back for rework

- **GIVEN** a unit that needs a same-repo unit, and that parent is sent back for rework
- **WHEN** the pass looks for units to start
- **THEN** the dependent is paused as any dependent of that unit is, and returns when the parent is back in review

#### Scenario: A cross-repo parent

- **WHEN** a unit needs a unit in another repository that is in review
- **THEN** the dependent does not start until that unit has merged

#### Scenario: Only a Needs line changed

- **WHEN** an edit changes a `Needs:` line and nothing else in `tasks.md`
- **THEN** no planner call is made and the dependency applies on the next tick

#### Scenario: The word merged is not a qualifier

- **WHEN** a `Needs:` line carries the word `merged` straight after the group number
- **THEN** the line means the same as without it, and `abk tags` and `abk check` warn that the word is deprecated, without failing or stopping planning

#### Scenario: A Needs on the change's own group

- **WHEN** a `Needs:` line carrying the word `merged` names a group of its own change
- **THEN** `abk tags` reports an error: the groups of one change are ordered already

#### Scenario: A stored merge gate from before

- **GIVEN** a stored unit that carries a `merge_before` from an earlier version
- **WHEN** the next tick reads the store
- **THEN** the store loads, the key is dropped, and the unit waits only for what a dependency requires

#### Scenario: A target the chain already implies

- **GIVEN** a unit whose dependency chain already reaches the unit a `Needs:` line names
- **WHEN** the next tick applies the line
- **THEN** no dependency is added, the unit's dependencies are unchanged, and the line is not applied again on any later tick

### Requirement: The graph page marks a Needs dependency

The unit graph page SHALL draw a dependency written as a `Needs:` line with a thick edge labelled `needs`, and a dependency the
planner inferred without a label or the thick style, and a `Needs:` dependency the chain already implies SHALL
draw no edge at all, and the legend SHALL say so, so a reader can tell a stated
dependency from an inferred one.

#### Scenario: A Needs dependency

- **WHEN** a unit has a dependency written as a `Needs:` line
- **THEN** the page draws that edge thick and labelled `needs`

#### Scenario: An inferred dependency

- **WHEN** a unit depends on another through the planner's own dependency
- **THEN** the page draws that edge without the label or the thick style

#### Scenario: The line is removed

- **WHEN** a `Needs:` line is removed and the dependency is not otherwise asked for
- **THEN** the edge is gone at the next tick

#### Scenario: A Needs line the chain implies

- **GIVEN** a unit that needs a unit its own parent already depends on
- **WHEN** the page is drawn
- **THEN** no edge is drawn for the line, and the edge to the parent is plain
