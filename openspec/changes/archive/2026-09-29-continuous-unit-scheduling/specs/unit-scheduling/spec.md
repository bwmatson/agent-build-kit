# Spec Delta

## Purpose

Defines when a pass decides what to build: continuously, as slots free and
dependencies clear, rather than once at the start.

## ADDED Requirements

### Requirement: A pass keeps its build slots full

While a pass is running, the pipeline SHALL re-evaluate what may be built each
time a unit finishes, and start what fits in the free slots, until nothing is in
flight and nothing is ready. The rules that decide readiness — the dependency
rules, the stack depth cap and the concurrency cap — SHALL be unchanged and
SHALL be applied on every evaluation. A unit already started in the pass SHALL
NOT be started again.

#### Scenario: A chain whose parent reaches review

- **WHEN** a unit finishes and its child's dependencies now allow it to start
- **THEN** the child starts in the same pass, without waiting for unrelated
  units in that pass to finish

#### Scenario: A slow sibling in another repo

- **WHEN** one unit's build lasts far longer than another's, and work is ready
- **THEN** the free slots are used while the slow unit continues

#### Scenario: A unit re-queued during the pass

- **WHEN** a unit is set back to planned while a pass is running, and a slot is
  free
- **THEN** that pass starts it rather than leaving it for the next one

#### Scenario: The caps still hold

- **WHEN** re-evaluation finds more ready units than free slots, or a chain
  already extends past the depth cap
- **THEN** no more than the cap are building at once, and the over-deep chain
  waits, exactly as before this change

### Requirement: A pass notices what the code host reports while it runs

Each time a pass re-evaluates what to build, it SHALL first refresh what the
code host reports, so that a dependency merged during the pass can release the
unit waiting on it, and review feedback arriving during a long pass is not left
until the pass ends. A refresh that fails SHALL be skipped rather than stopping
the pass, as it is today. Planning SHALL stay once per pass.

#### Scenario: A cross-repo dependency merges mid-pass

- **WHEN** a unit's cross-repo dependency merges while the pass is running
- **THEN** the dependent unit becomes startable in that pass

#### Scenario: The code host is unreachable

- **WHEN** a refresh fails during a pass
- **THEN** the pass logs it and carries on building

### Requirement: A pass that must stop, stops

When building a unit reports that the pass should stop — an exhausted usage
window, say — the pipeline SHALL stop starting further units in that pass rather
than discarding the report, and SHALL let already-running builds finish. A pass
narrowed to particular units SHALL stay narrowed for every evaluation.

#### Scenario: A usage window is spent mid-pass

- **WHEN** a build reports the pass should stop
- **THEN** nothing further is started, and the builds already in flight are left
  to finish and commit their work

#### Scenario: A pass narrowed to one unit

- **WHEN** a pass is asked to build one named unit and that unit finishes,
  unblocking another
- **THEN** the other is not started by that pass
