## ADDED Requirements

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
