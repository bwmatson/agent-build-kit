## ADDED Requirements

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
