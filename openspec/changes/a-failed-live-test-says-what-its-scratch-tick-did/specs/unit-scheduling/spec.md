## ADDED Requirements

### Requirement: A tick that builds nothing says why for each candidate unit

When a pass starts no unit and no usage pause, deadlock or full queue is the reason it reports, the tick SHALL print `nothing ready to build` as its
first line and then one line for each candidate unit, a unit stored as planned, held or failed, giving its wait reason and what it waits on. The lines
SHALL come from the one function that decides wait reasons, SHALL show at most 10 units and SHALL end with `(+M more)` when more were left out, and the
units whose reason is `ready`, `slot`, `lease` or `backoff` SHALL come first. Printing them SHALL NOT change which units a pass starts, SHALL NOT change
a stored unit, and a failure to compute them SHALL leave the first line alone and SHALL NOT fail the tick.

#### Scenario: A blocked unit and a held one

- **GIVEN** a unit blocked on another unit and a unit held for a person, and nothing startable
- **WHEN** a tick runs
- **THEN** its first line is `nothing ready to build`, followed by a line naming the blocked unit with `blocked` and the unit it waits on, and a line naming the held unit with `needs_person`

#### Scenario: More candidates than the bound

- **GIVEN** fourteen candidate units
- **WHEN** a tick builds nothing
- **THEN** ten lines are printed, then `(+4 more)`

#### Scenario: A unit in review is not a candidate

- **GIVEN** a unit in review and no other unit
- **WHEN** a tick builds nothing
- **THEN** only the first line is printed

#### Scenario: The other reports are unchanged

- **GIVEN** a deadlock among the units, or a full queue, or a usage pause
- **WHEN** a tick builds nothing
- **THEN** the output is the deadlock report, the full-queue report or the pause line it was, with no per-unit lines added

#### Scenario: The reasons cannot be computed

- **GIVEN** the function that computes wait reasons raises
- **WHEN** a tick builds nothing
- **THEN** the output is the first line and one line naming the error, the tick succeeds and no unit changes

#### Scenario: The lines do not change what starts

- **GIVEN** the same stored units
- **WHEN** a pass runs with the lines and without them
- **THEN** it starts the same units
