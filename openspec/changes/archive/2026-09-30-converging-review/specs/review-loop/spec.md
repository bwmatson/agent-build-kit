# Spec Delta

## Purpose

Defines how a unit's review loop ends: what a verdict may say besides "approved"
and "not yet", what the reviewer knows about what a further round costs, and what
becomes of a unit whose rounds run out.

## ADDED Requirements

### Requirement: The reviewer knows what another round costs

Each review round SHALL tell the reviewer which round this is, how many remain,
and what happens when they run out: the work is neither merged nor kept, and the
next attempt starts from nothing. This SHALL be stated as information for the
judgement the reviewer already makes, not as pressure to approve work it would
otherwise reject.

#### Scenario: The last round

- **WHEN** the final round's review begins
- **THEN** the reviewer has been told it is the final one and what ending it
  without approval costs

### Requirement: A finding may be deferred instead of blocking

A verdict SHALL be able to approve while recording work that should still be
done, and the recorded items SHALL be written where the change's later units and
the person reviewing the pull request will see them, not only in a log. The
following SHALL NOT be deferrable, and the reviewer SHALL be told so: behaviour
that is wrong, a test that would pass whether or not the code is correct, a test
the task asked for and does not exist, and anything the command policy or the
push gate forbids.

#### Scenario: One optional observation left

- **WHEN** the only outstanding point is worth recording but not worth another
  round
- **THEN** the unit is approved and the point is recorded against the change

#### Scenario: Something that may not wait

- **WHEN** the outstanding point is a correctness problem or a test that does not
  test what it claims
- **THEN** it blocks approval and is not recordable as a follow-up

### Requirement: A problem that is a class, not an instance, goes to a person

When a round finds another instance of a kind an earlier round already raised,
and the kind is open-ended rather than a list that can be completed, the reviewer
SHALL say so and the unit SHALL be held for a person with that reasoning on its
record, rather than another round being spent on the next instance.

#### Scenario: An unbounded list

- **WHEN** successive rounds each find a further way to reach the same forbidden
  effect, and no list of them can be complete
- **THEN** the unit is held, and its record says the approach needs changing
  rather than naming only the latest instance

### Requirement: A repeated disagreement goes to a person

When the builder has declined a point with a reason and the reviewer judges that
the reason does not hold, the unit SHALL be held for a person rather than a third
exchange being spent on that point.

#### Scenario: The builder declines twice

- **WHEN** a point is raised again after the builder declined it with a stated
  reason
- **THEN** the unit is held with both positions on its record

### Requirement: Spent rounds leave work in a person's hands

When the rounds run out with blocking work outstanding, the pipeline SHALL push
the branch, make its outstanding points visible on its pull request, and hold the
unit for a person — never discard the work or leave it only in a local worktree.
Nothing SHALL be merged: only a commit review approved may merge, as before.

#### Scenario: The budget is spent

- **WHEN** the last round ends without approval and with blocking points
- **THEN** the branch is pushed, the open points appear on its pull request, and
  the unit is held rather than failed

#### Scenario: What holding does not permit

- **WHEN** a unit is held this way
- **THEN** no commit is merged and nothing is marked approved
