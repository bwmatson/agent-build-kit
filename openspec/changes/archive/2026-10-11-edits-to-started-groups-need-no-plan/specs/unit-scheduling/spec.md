## ADDED Requirements

### Requirement: An edit to groups that have all started asks the planner for nothing

When a change's `tasks.md` differs from its recorded plan and every group of the change is claimed by a unit that has started (in flight, failed,
held, merged or satisfied), the pipeline SHALL record the new content as planned, with no failed attempts, and SHALL NOT call the planner. A unit
that is requeued SHALL read the edited group text from `tasks.md`. A tick after the edit SHALL make no call.

#### Scenario: Text edited on a failed unit's group

- **GIVEN** a change whose only group is built by a failed unit
- **WHEN** the text of that group is edited and the change is planned
- **THEN** the planner is not asked, the new content is recorded as planned with no failed attempts, and the unit's next run reads the edited text

#### Scenario: Text edited on a merged unit's group

- **GIVEN** a change whose groups are all built by merged units
- **WHEN** the text of a group is edited and the change is planned
- **THEN** the planner is not asked and the new content is recorded as planned

#### Scenario: A tick after the edit

- **GIVEN** an edit recorded without a planner call
- **WHEN** a tick plans
- **THEN** the planner is not asked

#### Scenario: A group still to plan

- **GIVEN** a change with one group no started unit claims
- **WHEN** it is planned after an edit
- **THEN** the planner is asked, with the started groups passed as built

### Requirement: A tag change under a started unit is reported and not applied

When a started unit's stored repo, tier or flag differs from the tags of the groups it carries, the pipeline SHALL report the unit, the difference
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

### Requirement: The planner is told which groups are taken

The planner's instructions SHALL say that groups marked as built are taken, are never to be claimed, and get no unit; and the text of the change sent to
it SHALL mark the heading of each group a started unit builds with `(built by <unit id>)` and no other heading. A plan that claims a built group SHALL
still be refused and nothing stored for it.

#### Scenario: The rule and the marker

- **GIVEN** a started unit that builds one group of a change
- **WHEN** the planner's prompt is built
- **THEN** it states the rule, and only that group's heading is marked `(built by <unit id>)`

#### Scenario: A planner that claims a built group

- **GIVEN** a planner reply with a unit claiming a group a started unit builds
- **WHEN** the plan is checked
- **THEN** it is refused and no unit is stored for it

### Requirement: A refused plan keeps its reason

A refused plan SHALL store the unit ids the planner returned and the reason it was refused in the change's plan record, not the planner's full reply, and
a bare `abk replan` SHALL show the reason beside the plan state. A later successful plan SHALL clear it.

#### Scenario: The reason is shown

- **GIVEN** a plan refused because it claimed a built group
- **WHEN** `abk replan` is run with no selector
- **THEN** the change's line shows the failing state and the reason

#### Scenario: The reason is cleared

- **GIVEN** a record with a refusal reason
- **WHEN** the change is next planned successfully
- **THEN** the record has no reason

## MODIFIED Requirements

### Requirement: A person can plan a change again on demand

`abk replan` SHALL plan the changes it is given, or selects with `--all` or `--failed`, now, whatever the recorded hash says: it SHALL remove each
selected change's recorded plan, run the planner for those changes only, and link the `Needs:` lines as a tick does. A unit id SHALL be accepted
and mapped to its change. With no selector it SHALL list each change with the state of its plan, and the reason when its last plan was refused, and
plan nothing. `--forget` SHALL remove the
records, make no planner call, and leave the planning to the next tick. It SHALL refuse a name that is not a change, a change without a
`tasks.md` and a change whose task groups have tag errors, and plan nothing for them. Its exit status SHALL be 0 when every selected change
planned, 1 when any failed or was refused, and 2 for a usage error. A change whose every group belongs to a started unit SHALL be recorded without a
planner call and reported as such. A tick SHALL be unchanged: it SHALL plan a change only when its `tasks.md`
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
- **THEN** it lists each change with the state of its plan and the reason when its last plan was refused, plans nothing and exits with the usage status

#### Scenario: A change that cannot be planned

- **WHEN** the name is not a change, the change has no `tasks.md`, or its task groups have tag errors
- **THEN** the command says why, plans nothing for it, and exits with status 1

#### Scenario: A tick skips an unchanged change

- **GIVEN** a change whose recorded plan matches its `tasks.md` and succeeded
- **WHEN** a tick plans
- **THEN** the planner is not asked

#### Scenario: A change with nothing left to plan

- **GIVEN** a change whose every group belongs to a started unit
- **WHEN** `abk replan` is run with its name
- **THEN** the planner is not asked, the command says every group is built by a started unit, and the plan is recorded
