## ADDED Requirements

### Requirement: A plan made under other ceilings or another review policy is stale and is shown as stale

abk SHALL record, with each change's plan, a digest of the ceilings and the `review:` section it was planned under, kept apart from
the digest of the change's `tasks.md`. A plan SHALL be stale when that policy digest is missing or differs from the one now in
force. `abk status`, the listing `abk replan` prints and the tick SHALL each say which plans are stale. A tick SHALL NOT plan a
change because its plan is stale, and a stale plan SHALL NOT by itself keep ticks busy.

#### Scenario: The ceilings changed

- **GIVEN** a change planned under `ceilings.full: 750` and an `abk.yaml` that now says `ceilings.full: 900`
- **WHEN** `abk status` runs
- **THEN** it prints a line naming the change and saying its plan is stale because the ceilings changed

#### Scenario: A plan from before the review policy

- **GIVEN** a plan record with no policy digest
- **WHEN** `abk replan` is run with no arguments
- **THEN** the listing shows the change as stale, saying it was planned before the review policy

#### Scenario: A tick does not spend planner calls on it

- **GIVEN** three stale plans whose `tasks.md` files have not changed
- **WHEN** a tick runs
- **THEN** it reports the three as stale, makes no planner call, and a tick with nothing else to do reports no work

### Requirement: `abk replan --report` shows what a migration would cost and reads nothing it must not

`abk replan --report [CHANGE ... | --all]` SHALL make no model call and write nothing. For each selected active change it SHALL
print the plan state (`current`, `stale` with the reason, or the states the `abk replan` listing already gives), the number of units
that have started and the number that have not, the task groups each carries, and whether a replan would call the planner: one call,
or none when every group is already taken by a started unit or by another change's planned unit. It SHALL print the total number of
planner calls and exit 0.

#### Scenario: A partly started change

- **GIVEN** a stale change with one merged unit, one running unit and two planned units
- **WHEN** `abk replan --report` names it
- **THEN** the report says two started and two unstarted, that a replan would make one planner call, and no planner call is made

#### Scenario: Every group is taken

- **GIVEN** a stale change whose every group is carried by a started unit
- **WHEN** the report runs
- **THEN** it says a replan would ask nothing of the planner, and the total counts none for it

#### Scenario: Nothing is written

- **WHEN** the report runs over any selection
- **THEN** the unit store, the plan records and every other file under the state directory are byte for byte what they were

### Requirement: `abk replan --dry-run` shows what each change's units would become and writes nothing

`abk replan --dry-run [CHANGE ... | --all | --stale | --failed]` SHALL ask the planner as a replan does, and SHALL write neither the
unit store nor the plan records nor any state file. For each change it SHALL print the units the plan would store, each with its id,
the groups it carries, its expected review tier, its estimated lines against the ceiling for that tier, the joins that would be
made, each started unit left as it is, and each unit that would be dropped to `unplanned`. It SHALL print the number of planner
calls before making them. A plan the planner refuses SHALL be printed with its reason and the units it returned, and the command
SHALL exit 1.

#### Scenario: A preview of a larger plan

- **GIVEN** a change of four small groups, planned before as four 150-line units under a 750 ceiling
- **WHEN** `abk replan --dry-run` is run with a stand-in planner that now returns one unit expected `light` with 600 lines
- **THEN** the output lists that unit with its tier and `600 of 2000`, lists the four old units as becoming `unplanned`, and the unit store is unchanged

#### Scenario: Nothing is stored

- **WHEN** a dry run completes, or the planner fails during it
- **THEN** the unit store, `planned.json` and the other state files are byte for byte what they were

#### Scenario: A refused plan

- **GIVEN** a planner reply that claims a group a merged unit already built
- **WHEN** the dry run reads it
- **THEN** the output gives the refusal reason and the returned unit ids, and the exit status is 1

### Requirement: A replan changes only a change's unstarted work, and a refused plan leaves the old plan standing

A replan SHALL leave every unit that has started with its state, branch, pull request and groups, and SHALL give the planner those
groups as built. When the plan is refused or fails, the stored units SHALL be as they were, the plan record SHALL keep the policy
digest of the plan that stands (so the change still reads as stale), and the command SHALL print the reason and that the old plan
stands. The failed attempt SHALL count against the change's plan attempts as any failed plan does.

#### Scenario: A partly started change

- **GIVEN** a change with a merged unit, a unit in review and two planned units
- **WHEN** it is replanned under new ceilings
- **THEN** the merged unit and the unit in review keep their state and branches and are reported as kept, and only the two planned units take the new shape

#### Scenario: A refused plan

- **GIVEN** a stale change and a planner reply the checks refuse
- **WHEN** `abk replan` runs for it
- **THEN** its units in the store are unchanged, the output gives the refusal reason and says the old plan stands, the plan record has used one attempt, and the change still reads as stale

### Requirement: Units that a replan would drop are listed, and dropped only when a person accepts it

When a replan would leave a unit of the change `unplanned`, abk SHALL print each such unit with its id, state and groups, and SHALL apply nothing for that change unless `--accept-unplanned` is given; it SHALL exit 1 for a change it did not apply. A change whose plan drops no unit SHALL need no flag. The planner SHALL be called once for the change, whether the plan is then applied or not.

#### Scenario: Drops without the flag

- **GIVEN** a change whose new plan omits two planned units
- **WHEN** `abk replan` runs without `--accept-unplanned`
- **THEN** both units are listed, the store is unchanged for that change, the planner was called once, and the exit status is 1

#### Scenario: Drops accepted

- **WHEN** the same replan runs with `--accept-unplanned`
- **THEN** the new plan is stored, the two units are `unplanned`, and the planner was called once

#### Scenario: No drops

- **GIVEN** a change whose new plan keeps every unit
- **WHEN** `abk replan` runs without the flag
- **THEN** the plan is stored

### Requirement: A migration runs by priority, a few changes at a time

`abk replan --stale` SHALL select every change whose plan is stale, and `--limit N` SHALL keep the first N of any selection, ordered
by the most urgent priority among the change's groups and then by name. A change waiting for an outage whose next try is ahead, and a
change that has given up on its current text, SHALL be skipped and listed with the reason. The first change that meets an outage
SHALL end the run, say that the rest were not tried, and use no plan attempt.

#### Scenario: The most urgent first

- **GIVEN** five stale changes, of which two have `Priority: 1`
- **WHEN** `abk replan --stale --limit 2` runs
- **THEN** exactly the two priority 1 changes are planned and the other three are listed as not yet planned

#### Scenario: A change that gave up is skipped

- **GIVEN** a stale change whose plan has used all its attempts on its current text
- **WHEN** `abk replan --stale` runs
- **THEN** it is listed as skipped with `--failed` named as the way to try it again, and the planner is not called for it

#### Scenario: The service is down

- **GIVEN** a planner that reports the model service unavailable on the first change
- **WHEN** `abk replan --stale --limit 3` runs
- **THEN** the run stops after that change, says the other two were not tried, and no attempt is used

### Requirement: The authoring guidance matches the per-tier ceilings

The `abk-authoring` skill SHALL say that a task group no longer needs to be split to fit a single 750-line ceiling, that the
planner sizes a unit by the review tier it expects, and that each group SHALL say in its tasks which files, boundaries or behaviours
it touches so a tier can be estimated. The text in the framework's skills and its mirror in the planning repo's skills SHALL agree.

#### Scenario: The skill text

- **WHEN** the skill's text is read
- **THEN** it contains the guidance above and no advice to split groups to stay under 750 lines
