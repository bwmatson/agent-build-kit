## ADDED Requirements

### Requirement: A conflict that stands on the trunk is moved by the restack first

Where a unit in review is based on the trunk and the host reports its pull
request as conflicting, the first attempt SHALL be the stack move: the branch
SHALL be replayed onto the trunk's tip with the conflict resolver scoped to
the files that conflict and recorded resolutions replayed, as for a unit whose
parent merged. The attempt SHALL follow the stack move's outcomes: a clean move
of an approved head with an unchanged diff SHALL be pushed and the unit SHALL
stay in review; a move that needed the resolver or changed the diff SHALL leave
the unit planned for review before anything is pushed. A conflict the stack move
cannot settle, a second attempt at the same base tip, a unit that is not based
on the trunk and a unit whose thread cannot take the event SHALL go to the
conflict rework. The attempt SHALL run only while the unit's branch is free,
SHALL leave the event for the next poll when it is held, and SHALL ask the usage
guard before the resolver as any resolver call does, so that under a usage
pause a clean move proceeds and one that needs the resolver waits.

#### Scenario: A clean move

- **GIVEN** a trunk-based unit in review with an approved head and a conflict
  the trunk's new commits made
- **WHEN** the stack move replays its commits cleanly
- **THEN** the branch is pushed with the lease, a comment says it was restacked,
  and the unit stays in review with no agent run

#### Scenario: A move that needed the resolver

- **WHEN** the replay conflicts and the scoped resolver settles it
- **THEN** nothing is pushed, and the unit is planned for review of the resolved
  move

#### Scenario: A conflict the move cannot settle

- **WHEN** the stack move leaves a conflict it cannot settle
- **THEN** the unit is sent back through the conflict rework, and the attempt is
  counted once

#### Scenario: The second attempt at the same base tip

- **GIVEN** a stack move that pushed a head at a base tip
- **WHEN** the host still reports a conflict after that push at the same tip
- **THEN** the next attempt is the conflict rework

#### Scenario: A branch that is being built

- **WHEN** the unit's branch is held by a run
- **THEN** nothing is moved, no attempt is recorded and the event comes again
  next poll

#### Scenario: Under a usage pause

- **GIVEN** a usage pause in force
- **WHEN** a conflicting unit is dispatched and its move is clean
- **THEN** it is moved and pushed, and when it needs the resolver it is left
  for the poll after the pause, with no attempt counted
