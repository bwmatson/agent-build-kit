## ADDED Requirements

### Requirement: A unit whose tier 2 split is held is not started

A planned unit that has never started and whose split (recorded when it was planned) is held for its repo SHALL NOT be started: the round SHALL
make no worktree, no branch and no model call for it, and SHALL NOT resume, rework or restack it, because it has no work. A split is held when the
held set the tier 2 run reads says so: the configuration's `hold: true`, an entry in the state file, or an entry a gate wrote, with `hold: false`
in the configuration winning over the file; the start decision SHALL NOT ask a gate. The unit SHALL be started by the same round that finds the
split no longer held: the configuration line removed or set to `false`, `abk tier2 release`, or the removal or expiry of a gate's entry. A unit in
`rest` SHALL be gated only when `rest` itself is held. A unit that has started (a pull request, a branch or a pushed commit), a unit in review, a
rework, a resume, a unit failed or held by a person, and a unit parked at tier 2 SHALL NOT be affected: the parking stays as it is and is the
backstop. A unit that depends on a gated unit SHALL wait on it as on any unbuilt unit. A unit whose split is no longer declared for its repo SHALL
NOT be gated. `hold: false` in the configuration SHALL release a unit whatever the file holds.

#### Scenario: Not started while held

- **GIVEN** the split `acp` held and a ready, never-started unit in `acp`
- **WHEN** a round runs
- **THEN** no worktree, branch or model call is made for it and it stays planned

#### Scenario: Another unit starts

- **GIVEN** `acp` held, a ready unit in `acp` and a ready unit in `rest`
- **WHEN** a round runs
- **THEN** the unit in `rest` starts and the one in `acp` does not, and a free slot goes to the next ready unit

#### Scenario: Started the round the hold ends

- **GIVEN** a gated unit and the split released by `abk tier2 release`, by removing `hold: true`, or by the gate removing its entry
- **WHEN** the next round runs
- **THEN** the unit is ready and starts in that round, if a slot and room allow

#### Scenario: A hold in the configuration beats the file

- **GIVEN** an entry in the state file holding `acp` and `hold: false` for `acp` in the configuration
- **WHEN** a round runs
- **THEN** the unit in `acp` starts

#### Scenario: A started unit is not held back

- **GIVEN** a unit in `acp` that already has a branch and a pushed commit, and `acp` held
- **WHEN** a round runs
- **THEN** the unit is rebased, reworked or resumed as without the hold, and at tier 2 it parks as before

#### Scenario: A dependant waits

- **GIVEN** a unit that depends on a gated unit
- **WHEN** a round runs
- **THEN** it does not start and waits on the gated unit as on any unbuilt unit

#### Scenario: A split not declared any more

- **GIVEN** a planned unit in a split its repo no longer declares
- **WHEN** a round runs
- **THEN** it is not gated

#### Scenario: Rest held

- **GIVEN** `rest: {hold: true}` and a never-started unit with no `Split:` line
- **WHEN** a round runs
- **THEN** it is not started, as a unit in any held split is not

### Requirement: A unit not started because of a hold waits on a reason of its own and takes no place

A gated unit SHALL have the wait reason `split`, and its text SHALL read "waiting for tier 2 split <name>" with the hold's reason and its deadline
as the held-set listing gives them. The reason SHALL be given after the reasons that it waits on another unit or on a lease or a backoff (a unit that
waits on a parent is `blocked` until the parent merges) and before a usage pause and the ready reasons. A gated unit SHALL NOT be counted as in
progress, SHALL NOT draw on the room under `max_units_in_progress` or on a build slot, and SHALL NOT make a project's queue read as full; a ready
unit behind it in the same project SHALL start in the room it would have taken. Dependants of a gated unit SHALL NOT lend it priority while it is
left out. A gated unit SHALL be one of the units the round's log and the wait decision log record with this reason.

#### Scenario: The reason

- **GIVEN** a gated unit in `acp`, held with the reason "model budget out"
- **WHEN** the wait reasons are read
- **THEN** its reason is `split` and its text is "waiting for tier 2 split acp" with the hold's reason

#### Scenario: A parent first

- **GIVEN** a gated unit whose parent has not merged
- **WHEN** the wait reasons are read
- **THEN** it is `blocked` on the parent, and `split` once the parent has merged

#### Scenario: Not counted

- **GIVEN** a limit of 2 units in progress, two gated units and one in progress
- **WHEN** a round runs
- **THEN** the count in progress is 1 and a ready unit of `rest` starts

#### Scenario: Not a slot

- **GIVEN** four build slots and a gated unit that is the most urgent
- **WHEN** a round runs
- **THEN** four ready units of other splits start, and the gated unit holds none of the slots

### Requirement: The listings show the units a hold keeps from starting

`abk status` SHALL list a gated unit with the other wait reasons, naming its split and the hold, and SHALL say "released, starts this round" for a
unit whose split is no longer held and which has not been started yet. `abk tier2 status` SHALL list, under each held split, the units waiting on it:
those parked at tier 2 and those not started, each with its id and repo. The unit graph SHALL draw a gated unit as waiting, and the graph legend
and the description of that state SHALL say that a unit may wait on a held tier 2 split. A repo that declares no split SHALL show none of this.

#### Scenario: The status line

- **GIVEN** a gated unit in `acp`
- **WHEN** `abk status` runs
- **THEN** it lists the unit as waiting for tier 2 split `acp` with the hold's reason

#### Scenario: Per split

- **GIVEN** `acp` held, one unit parked at tier 2 and one not started
- **WHEN** `abk tier2 status` runs
- **THEN** both are listed under `acp`, told apart as parked and not started

#### Scenario: The graph

- **GIVEN** a gated unit
- **WHEN** the graph is drawn
- **THEN** it is drawn as waiting, and the legend says it may be waiting on a held tier 2 split

### Requirement: A declaration that differs from the unit's tests is a warning and the unit still parks

`abk tier2 check` SHALL warn, for each unit it can find the own tests of, about an own test that is in a split other than the split its group
declares, naming the group (change and number), the declared split and the split the test is in; it SHALL NOT make the exit status non-zero by
this alone. A unit declared `rest` or another split that is found at tier 2 to hold tests of a held split SHALL park as it does now, with no change
to that path. A unit with no `Split:` line whose tests are in `rest` SHALL give no warning.

#### Scenario: A mismatch

- **GIVEN** a group declared `rest` whose own test is selected by the marker of `acp`
- **WHEN** `abk tier2 check` runs
- **THEN** it prints a warning naming the group, `rest` and `acp`, and exits as it would without the warning

#### Scenario: The backstop

- **GIVEN** such a unit, started because `acp` was not held, and `acp` held by the time it reaches tier 2
- **WHEN** its tier 2 runs
- **THEN** it parks for `acp` exactly as before this change

#### Scenario: Agreement

- **GIVEN** a group declared `acp` whose own tests are all in `acp`
- **WHEN** `abk tier2 check` runs
- **THEN** it prints no warning for that group
