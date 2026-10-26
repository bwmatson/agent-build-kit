## ADDED Requirements

### Requirement: A unit's id comes from the groups it carries, not from the planner

After a plan has passed every check, the program SHALL give each unit of the change being planned the id `<change>/<L>`, `L` being the lowest task group
number of that change the unit carries; groups of other changes a unit carries by a join SHALL NOT count. The `id` a planner reply gives a unit SHALL be
read as a label, valid only inside that reply: a `depends_on` entry that equals a label SHALL be replaced by the id given to that unit, in order and
without repeats, and an entry that equals no label SHALL be left, as a stored unit's id. The label SHALL NOT be stored. A reply that uses `<change>/<n>`
as its labels SHALL be accepted. A label SHALL be unique in the reply. A unit that carries no group of its change SHALL keep its label as its id. A
started unit SHALL never be given another id, and a join SHALL NOT renumber the unit it joins onto.

#### Scenario: The id follows the lowest group

- **GIVEN** a reply whose units carry groups [1, 2], [3] and [4, 5] under the labels `u1`, `u2` and `u3`
- **WHEN** the plan is read
- **THEN** the units are `x/1`, `x/3` and `x/4`

#### Scenario: Different labels, same groups, same id

- **GIVEN** two replans of one change that group the same groups in the same way, the first labelled `u1`, `u2` and the second `a`, `b`
- **WHEN** both are read against the store the first one left
- **THEN** both give the same ids and the second changes no unit's id

#### Scenario: The old form is accepted

- **GIVEN** a reply whose units are labelled `x/7` for groups [3] and `x/9` for groups [4], and the second depends on `x/7`
- **WHEN** the plan is read
- **THEN** the units are `x/3` and `x/4`, and the second depends on `x/3`

#### Scenario: Joined groups do not count

- **GIVEN** a plan unit of `x` for group 5, in a store where an unstarted unit of `y` has taken `x` group 2 by a join
- **WHEN** the plan is read
- **THEN** the unit is `x/5`

#### Scenario: A reference to a stored unit is left

- **GIVEN** a reply in which a unit depends on `x/1`, which is a merged unit and not a label of the reply
- **WHEN** the plan is read
- **THEN** the dependency is still `x/1`

#### Scenario: A split keeps the lower id on the lowest group

- **GIVEN** an unstarted unit `x/3` for groups [3, 4] and a reply with a unit for group 3 and a unit for group 4
- **WHEN** the plan is read
- **THEN** the first is `x/3`, which the plan rewrites in place, and the second is `x/4`

#### Scenario: A join does not renumber

- **GIVEN** an unstarted unit `y/4` that takes `x` group 2 by a join
- **WHEN** the join is stored
- **THEN** the unit is still `y/4`

#### Scenario: A started unit keeps its id

- **GIVEN** a running unit `x/2` for groups [3, 4] and a reply that plans the remaining groups
- **WHEN** the plan is read and stored
- **THEN** `x/2` has the same id, state and groups, and no planned unit is given its groups or its id

### Requirement: A unit with the same groups as a stored unit keeps its id

Before the rule above applies, a planned unit whose set of the change's own groups equals that of a stored unit of the change that has not started
(`planned` or `unplanned`, with no branch, pull request, pushed commit or approval, and not retired) SHALL be given that unit's id, whatever its
number. Each stored unit SHALL be matched to at most one planned unit, the lowest id first, and every match SHALL be made before any id is computed by
the rule. A stored unit that has started SHALL NOT be matched. A second replan of the same groups SHALL change no id.

#### Scenario: A legacy id is kept

- **GIVEN** an unstarted unit `x/4` for groups [3, 4], the id the planner once chose, and a reply that groups [3, 4] in one unit
- **WHEN** the plan is read
- **THEN** the unit is `x/4` and nothing is renumbered

#### Scenario: A match is owed its id

- **GIVEN** an unstarted `x/2` for groups [3, 4] and a reply with a unit for groups [3, 4] and a unit for group 2
- **WHEN** the plan is read
- **THEN** the first is `x/2` and the second does not take it

#### Scenario: Two replans

- **GIVEN** a plan stored by one replan
- **WHEN** the same change is replanned with the same groups
- **THEN** no unit is given a different id, and none becomes `unplanned`

#### Scenario: A started unit is not matched

- **GIVEN** a running unit for groups [3] and a reply that also asks for groups [3] under a label
- **WHEN** the plan is read
- **THEN** the plan is refused for claiming a group a started unit carries, as before, before any id is given

### Requirement: An id that is taken is not given to other work

The id `<change>/<L>` SHALL be used only when it is free: it is not an id of a retired unit, not already given to another unit of the reply, and not the
id of a stored unit unless that unit has not started and no other planned unit of the reply matches its groups, in which case the plan rewrites that unit
in place as a plan does for any id. A merged, closed, satisfied, running, in review, failed, held, retired or `unplanned` unit with work SHALL keep its id
for itself. When the id is not free the unit SHALL be given the smallest free integer greater than the highest task group number of the change and than
the leading integer of every stored id of the change, so the id is always `<change>/<integer>`; the same store and reply SHALL give the same id. A
retired unit's id SHALL never be given again.

#### Scenario: A retired id is skipped

- **GIVEN** a retired unit `x/3` and a reply with a unit for group 3 and the highest group 5
- **WHEN** the plan is read
- **THEN** the unit is `x/6`, never `x/3`

#### Scenario: A started unit holds its id

- **GIVEN** a running unit `x/2` for groups [3, 4] and a reply with a unit for group 2
- **WHEN** the plan is read
- **THEN** the unit is not `x/2`; it is `x/` followed by an integer above 4 and above every stored number, and `x/2` is unchanged

#### Scenario: An unstarted unit with other groups is reused in place

- **GIVEN** an unstarted `x/3` for groups [3, 4] and a reply that leaves it out and has a unit for group 3 alone
- **WHEN** the plan is read and stored
- **THEN** the unit is `x/3`, rewritten by the plan, and no second `x/3` exists

#### Scenario: The fallback is a plain number

- **GIVEN** a merged unit `x/3` and a reply with a unit for group 3
- **WHEN** the plan is read
- **THEN** the id's last segment is an integer, `unit_number` reads it, and the run log, transcript and branch names are formed as for any other id

#### Scenario: A split piece id is not renamed

- **GIVEN** a plan made to split a held unit, whose pieces are named by that request
- **WHEN** the plan is read
- **THEN** the pieces keep the ids the request gives them

### Requirement: The planner is told its ids are labels, and a label cannot stand for a taken unit

The planner prompt SHALL give the reply shape with `"id": "<label>"`, SHALL say that the program assigns each unit's id from its groups, that the label is
the planner's own for one reply, short and unique, that a unit of the reply is referred to by its label in `depends_on` and `needs_less_urgent`, and
that a unit already in flight is referred to by the id shown. A reply with a duplicate label SHALL be refused. A reply with a label that is the id of a
retired unit, or of a stored unit that has started or finished, SHALL be refused naming it, as an invalid plan; a label that is the id of a stored unit
that has not started SHALL be accepted. A join SHALL name stored units only and SHALL pass through unchanged. An excuse in `needs_less_urgent` SHALL be
read by label.

#### Scenario: The prompt

- **WHEN** the prompt is built
- **THEN** it shows `"id": "<label>"`, says the program assigns the ids, and no longer shows `<change>/<n>` as the shape to return

#### Scenario: A duplicate label

- **GIVEN** a reply with two units labelled `u1`
- **WHEN** it is read
- **THEN** it is refused, naming `u1`

#### Scenario: A label that is a started unit's id

- **GIVEN** a running unit `x/2` and a reply that labels a new unit `x/2`
- **WHEN** it is read
- **THEN** it is refused, naming `x/2`

#### Scenario: A label that is a retired id

- **GIVEN** a retired unit `x/3` and a reply that labels a unit `x/3`
- **WHEN** it is read
- **THEN** it is refused as invalid, naming the id

#### Scenario: A join is not rewritten

- **GIVEN** a reply with a join onto a stored unit `y/1` and a unit labelled `u1`
- **WHEN** the plan is read
- **THEN** the join still names `y/1`

#### Scenario: An excuse by label

- **GIVEN** a unit that depends on the unit labelled `u2`, less urgent and unstarted, with `needs_less_urgent` for `u2` and a reason
- **WHEN** the plan is read
- **THEN** it is accepted and the dependency is the id given to `u2`

## MODIFIED Requirements

### Requirement: A refused plan keeps its reason

A failed plan SHALL store the reason in the change's plan record, whether the planner returned a plan that was refused or the attempt raised or could not be made, and a refused plan SHALL store as well the labels the planner gave its units (the ids of the units when the reply used them as labels), not the planner's full reply. The reason SHALL be the first line of the error, at most 300 characters, with secrets removed by the same redaction as printed output, and a bare `abk replan` SHALL show the reason beside the plan state. A later successful plan SHALL clear it.

#### Scenario: The reason is shown

- **GIVEN** a plan refused because it claimed a built group
- **WHEN** `abk replan` is run with no selector
- **THEN** the change's line shows the failing state and the reason

#### Scenario: The reason is cleared

- **GIVEN** a record with a refusal reason
- **WHEN** the change is next planned successfully
- **THEN** the record has no reason

#### Scenario: A call that failed keeps its reason

- **GIVEN** a planner call that ends in an ordinary failure with a message of several lines and more than 300 characters
- **WHEN** the attempt is recorded
- **THEN** the attempt is counted and the record keeps the first line of the message cut to 300 characters

#### Scenario: A secret does not reach the record

- **GIVEN** a failure whose message contains a value the redaction set knows
- **WHEN** the attempt is recorded
- **THEN** the stored reason does not contain it
