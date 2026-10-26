# split-start-gate Specification

## Purpose
TBD - created by archiving change a-unit-in-a-held-split-is-not-started. Update Purpose after archive.

## Requirements

### Requirement: A unit whose e2e-test split is held is not started

A planned unit that has never started and whose split (recorded when it was planned) is held for its repo SHALL NOT be started: the round SHALL
make no worktree, no branch and no model call for it, and SHALL NOT resume, rework or restack it, because it has no work. A split is held when the
held set the e2e-test run reads says so: the configuration's `hold: true`, an entry in the state file, or an entry a gate wrote, with `hold: false`
in the configuration winning over the file; the start decision SHALL NOT ask a gate. The unit SHALL be started by the same round that finds the
split no longer held: the configuration line removed or set to `false`, `abk e2e-test release`, or the removal or expiry of a gate's entry. A unit in
`rest` SHALL be gated only when `rest` itself is held. A unit that has started (a pull request, a branch or a pushed commit), a unit in review, a
rework, a resume, a unit failed or held by a person, and a unit parked at e2e-test SHALL NOT be affected: the parking stays as it is and is the
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

- **GIVEN** a gated unit and the split released by `abk e2e-test release`, by removing `hold: true`, or by the gate removing its entry
- **WHEN** the next round runs
- **THEN** the unit is ready and starts in that round, if a slot and room allow

#### Scenario: A hold in the configuration beats the file

- **GIVEN** an entry in the state file holding `acp` and `hold: false` for `acp` in the configuration
- **WHEN** a round runs
- **THEN** the unit in `acp` starts

#### Scenario: A started unit is not held back

- **GIVEN** a unit in `acp` that already has a branch and a pushed commit, and `acp` held
- **WHEN** a round runs
- **THEN** the unit is rebased, reworked or resumed as without the hold, and at e2e-test it parks as before

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

A gated unit SHALL have the wait reason `split`, and its text SHALL read "waiting for e2e-test split <name>" with the hold's reason and its deadline
as the held-set listing gives them. The reason SHALL be given after the reasons that it waits on another unit or on a lease or a backoff (a unit that
waits on a parent is `blocked` until the parent merges) and before a usage pause and the ready reasons. A gated unit SHALL NOT be counted as in
progress, SHALL NOT draw on the room under `max_units_in_progress` or on a build slot, and SHALL NOT make a project's queue read as full; a ready
unit behind it in the same project SHALL start in the room it would have taken. Dependants of a gated unit SHALL NOT lend it priority while it is
left out. A gated unit SHALL be one of the units the round's log and the wait decision log record with this reason.

#### Scenario: The reason

- **GIVEN** a gated unit in `acp`, held with the reason "model budget out"
- **WHEN** the wait reasons are read
- **THEN** its reason is `split` and its text is "waiting for e2e-test split acp" with the hold's reason

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
unit whose split is no longer held and which has not been started yet. `abk e2e-test status` SHALL list, under each held split, the units waiting on it:
those parked at e2e-test and those not started, each with its id and repo. The unit graph SHALL draw a gated unit as waiting, and the graph legend
and the description of that state SHALL say that a unit may wait on a held e2e-test split. A repo that declares no split SHALL show none of this.

#### Scenario: The status line

- **GIVEN** a gated unit in `acp`
- **WHEN** `abk status` runs
- **THEN** it lists the unit as waiting for e2e-test split `acp` with the hold's reason

#### Scenario: Per split

- **GIVEN** `acp` held, one unit parked at e2e-test and one not started
- **WHEN** `abk e2e-test status` runs
- **THEN** both are listed under `acp`, told apart as parked and not started

#### Scenario: The graph

- **GIVEN** a gated unit
- **WHEN** the graph is drawn
- **THEN** it is drawn as waiting, and the legend says it may be waiting on a held e2e-test split

### Requirement: A declaration that differs from the unit's tests is a warning and the unit still parks

`abk e2e-test check` SHALL warn, for each unit it can find the own tests of, about an own test that is in a split other than the split its group
declares, naming the group (change and number), the declared split and the split the test is in; it SHALL NOT make the exit status non-zero by
this alone. A unit declared `rest` or another split that is found at e2e-test to hold tests of a held split SHALL park as it does now, with no change
to that path. A unit with no `Split:` line whose tests are in `rest` SHALL give no warning.

#### Scenario: A mismatch

- **GIVEN** a group declared `rest` whose own test is selected by the marker of `acp`
- **WHEN** `abk e2e-test check` runs
- **THEN** it prints a warning naming the group, `rest` and `acp`, and exits as it would without the warning

#### Scenario: The backstop

- **GIVEN** such a unit, started because `acp` was not held, and `acp` held by the time it reaches e2e-test
- **WHEN** its e2e-test runs
- **THEN** it parks for `acp` exactly as before this change

#### Scenario: Agreement

- **GIVEN** a group declared `acp` whose own tests are all in `acp`
- **WHEN** `abk e2e-test check` runs
- **THEN** it prints no warning for that group

### Requirement: A parked unit whose group's Split changed away from its park is released once, as a rework

A pass SHALL compare each parked unit with the `Split:` of the groups it carries in the current `tasks.md`. A unit is parked when it is `planned`
with the cause `split_held` and a non-empty `parked_splits`, and is not in flight. When the groups it carries read as one split that differs from
the split the unit is stored in, and that split is none of the splits the unit is parked on, and it is not held for the unit's repo, the pass
SHALL end the park: it SHALL deliver the unit a requeue in rework mode (`RequeueReason.FROM_FAILURE`, not a resume) carrying an automatic note that
says the group's `Split:` changed from the old split to the new one, that the task text changed with it and that the groups' tasks are to be read
again; it SHALL clear `parked_splits`, `parked_sha` and `parked_snapshot` and set the unit's stored split to the new one; and it SHALL record the
release in the tick log and as a requeue in the unit's history. The unit SHALL be released once for a change: the same unit SHALL NOT qualify in
the next pass. A unit whose group still says its stored split, one whose group now says a split it is parked on, a unit in flight, a unit in any
other state, or in `planned` with another cause, SHALL NOT be read, changed or written. A unit whose groups do not read as one split, or whose
tasks file is refused, SHALL be left parked and unchanged. A pass SHALL NOT start the step in a dry run, which SHALL say what it would release.

#### Scenario: Split changed to claude_code, released and reworked once

- **GIVEN** a `planned` unit with cause `split_held`, stored split `acp`, `parked_splits` `["acp"]`, a `parked_sha` and a `parked_snapshot`, and a `tasks.md` whose group of the unit now says `Split: claude_code`
- **WHEN** a pass runs, and then a second pass runs
- **THEN** the first delivers one rework requeue with a note naming `acp`, `claude_code` and the group and saying the task text changed, the unit's parked fields are cleared and its stored split is `claude_code`, the tick log and the history say why, and the second delivers nothing to it

#### Scenario: Split unchanged, the unit stays parked

- **GIVEN** a unit parked on `acp` whose group still says `Split: acp`, and one stored `rest` and parked on `acp` by the backstop whose group says nothing
- **WHEN** a pass runs
- **THEN** neither is delivered anything or written to, and both are still parked

#### Scenario: Changed to the split it is parked on, the unit stays parked

- **GIVEN** a unit stored `rest` and parked on `acp` whose group is edited to `Split: acp`
- **WHEN** a pass runs
- **THEN** it is left parked and nothing is written

#### Scenario: Changed to another held split, the unit stays parked on that

- **GIVEN** a unit parked on `acp` whose group now says `Split: gpu`, with `gpu` held for its repo
- **WHEN** a pass runs, then `acp` is released and a pass runs, then `gpu` is released and a pass runs
- **THEN** the first two deliver nothing and leave the unit parked (the release of `acp` does not resume it onto its old tests), and the third reworks it once with a note naming `acp` and `gpu`

#### Scenario: A unit in flight is not touched

- **GIVEN** a unit in the in-flight set, a `running` unit, an `unplanned` unit with parked splits and a `planned` unit with cause `requeued`, each with a group whose `Split:` differs from its stored split
- **WHEN** a pass runs
- **THEN** none is read, delivered anything or written to

#### Scenario: A second round does not rework it again

- **GIVEN** the unit of the first scenario, reworked, whose e2e step then parks it again on the held split `claude_code`
- **WHEN** the next pass runs
- **THEN** the unit stays parked on `claude_code` and is not reworked a second time, because its group's split equals its stored split

#### Scenario: A refused delivery is retried

- **GIVEN** a qualifying unit whose branch is busy so that the delivery raises
- **WHEN** a pass runs and the next pass runs after the branch is free
- **THEN** the first leaves the unit's fields exactly as they were and the second delivers the rework

#### Scenario: A reworked unit runs the agent again

- **GIVEN** a unit released by this rule with the note stored as its guidance and work on its branch
- **WHEN** the tick runs the unit
- **THEN** it starts at `prepare` as a rework and the agent reads the note, and the e2e step is not run first

### Requirement: The status and a replan show a parked unit that follows its group's Split

`abk status` SHALL list a parked unit whose group's `Split:` changed and whose new split is held on its parked line, naming the new split, why it is
held and that the unit is reworked when it is released, and a unit it released SHALL appear as requeued with its history note. `abk replan` SHALL
run the pass's step after it plans and print one line for each unit it released, naming both splits. The release of an old split SHALL NOT resume a
unit whose group's split differs from its stored split and is not one it is parked on; only this rule releases it.

#### Scenario: The status says what the unit waits for

- **GIVEN** a unit parked on `acp` whose group now says `Split: gpu` while `gpu` is held
- **WHEN** `abk status` runs
- **THEN** its parked line says the group now says `gpu`, gives the hold's reason and says it is reworked when `gpu` is released, not "released, resumes this round"

#### Scenario: A replan releases it at once

- **GIVEN** the four-unit case: each unit parked on the held split `acp`, its group edited to `Split: claude_code`
- **WHEN** a person runs `abk replan` of the change
- **THEN** it prints a line for the unit with `acp` and `claude_code`, and the unit is reworked

#### Scenario: A replan of a change with nothing parked prints nothing new

- **GIVEN** a change none of whose units is parked
- **WHEN** `abk replan` runs
- **THEN** its output is what it was before this change

### Requirement: A unit parked on a split can be requeued for rework

`abk requeue UNIT` SHALL accept a unit that is `planned` with the cause `split_held` or a non-empty `parked_splits`, is not in flight, has no pull
request and no live run, when a mode that runs the agent again is given: `--rework`, with or without `--note` or `--note-file` and with no saved
failure needed, or `--restart`. It SHALL be delivered like any other requeue of a unit with a thread (the person's note stored as the unit's guidance;
with no thread the guidance stored and the unit set `planned` with the cause `requeued`), and only after the delivery SHALL it clear `parked_splits`,
`parked_sha`, `parked_snapshot`, the `split_held` cause and the unit's wait record. Its history SHALL carry a note naming the splits it was parked on
and the person's note. The unit SHALL then run from `prepare` as a rework, and a second `abk requeue` of it SHALL NOT find it parked. A delivery
refused because a step holds the branch SHALL leave the unit exactly as it was. A `running`, `in_review` or `merged` unit, a parked unit with a pull
request and a parked unit in flight SHALL still be refused, and nothing changed.

#### Scenario: A parked unit is requeued for rework, once

- **GIVEN** a `planned` unit with cause `split_held`, `parked_splits` `["acp"]`, a `parked_sha`, a `parked_snapshot` and a branch, no pull request, no run, and `acp` held
- **WHEN** a person runs `abk requeue UNIT --rework --note "retag the test; it uses a scripted agent"`, and then runs it again
- **THEN** the first is accepted and delivers one rework requeue with the note as guidance, `parked_splits`, `parked_sha` and `parked_snapshot` are empty, the cause is no longer `split_held`, the history entry names `acp` and the note, and the unit starts at `prepare`; the second is not treated as a parked unit

#### Scenario: A rework with no note is accepted

- **GIVEN** the unit above with no saved failure
- **WHEN** a person runs `abk requeue UNIT --rework`
- **THEN** it is accepted and requeued for rework, with an automatic guidance that says the unit was parked on `acp` and the agent is to run again

#### Scenario: A restart is accepted

- **GIVEN** the unit above
- **WHEN** a person runs `abk requeue UNIT --restart`
- **THEN** the unit's saved failure is cleared, its park is cleared and it starts again at the agent's step

#### Scenario: A unit in flight is refused

- **GIVEN** a parked unit whose branch a step holds
- **WHEN** a person runs `abk requeue UNIT --rework`
- **THEN** it is refused with "is being built" and its park, cause and fields are unchanged, and a requeue once the step has stopped is accepted

#### Scenario: A unit with a pull request is refused

- **GIVEN** a parked unit that has a pull request, and a `running`, an `in_review` and a `merged` unit
- **WHEN** a person runs `abk requeue --rework` on each
- **THEN** each is refused and nothing is changed

### Requirement: A plain requeue of a unit parked on a held split is refused

A plain `abk requeue UNIT` (resume) of a parked unit SHALL be refused while any split the unit is parked on is held for its repo, with a message that
says the unit is parked on those splits, gives why each is held, and says to give `--rework` (with a note saying what changed) or to release the
split; nothing SHALL be changed. When none of its parked splits is held, a plain requeue SHALL do what the release of a parked split does: deliver a
resume. A plain requeue of a parked unit whose group's `Split:` moved away from its stored split SHALL be refused, saying the pass reworks it. A note
with a plain requeue SHALL still be refused.

#### Scenario: Plain requeue while the split is held

- **GIVEN** a unit parked on `acp` while `acp` is held with a reason
- **WHEN** a person runs `abk requeue UNIT`
- **THEN** it is refused with a message that says the unit is parked on `acp` (held: that reason) and to give `--rework` with a note or release the split, and the unit is unchanged

#### Scenario: Plain requeue after the release

- **GIVEN** a unit parked on `acp` after `acp` was released
- **WHEN** a person runs `abk requeue UNIT`
- **THEN** a resume is delivered as the release would deliver it, or, with no thread, the unit is set `planned` with cause `requeued`

### Requirement: The status and the help say a parked unit can be requeued

After the requeue `abk status` SHALL NOT list the unit as waiting for the split, and SHALL show it as a requeued planned unit whose history carries the
note. `abk requeue --help`, `docs/cli.md` and the `abk-pipeline` skill SHALL say a unit parked on a held split is requeued with `--rework` or
`--restart`, that a plain requeue is refused while the split is held, and that running, in-review, merged, in-flight and pull-request units are still
refused.

#### Scenario: The status after the requeue

- **GIVEN** a unit parked on `acp` and listed as waiting for that split
- **WHEN** it is requeued with `--rework` and `abk status` runs
- **THEN** it has no waiting line and shows as requeued with the history note naming `acp`

#### Scenario: The help text

- **GIVEN** the installed `abk`
- **WHEN** a person runs `abk requeue --help` or reads `docs/cli.md`
- **THEN** both name a unit parked on a held split and the options that accept it
