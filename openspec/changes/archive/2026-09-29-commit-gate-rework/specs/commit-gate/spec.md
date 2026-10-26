# Spec Delta

## Purpose

Defines what happens when the target repository's own commit gate rejects a
unit's commit: the gate's output goes back to the author, bounded, and the gate
is never bypassed.

## ADDED Requirements

### Requirement: A gate that rewrote the files is retried without an agent

When a commit is rejected and committing again succeeds, the pipeline SHALL
treat that as the gate having fixed the work itself and carry on, without
spending an agent call and without reporting a problem.

#### Scenario: A formatter rewrites a file during the commit

- **WHEN** the gate reformats a staged file and rejects the commit
- **THEN** the commit is attempted again, succeeds, and the unit proceeds as if
  it had succeeded the first time

### Requirement: A gate that found something hands its output to the author

When a commit is still rejected after a retry, the pipeline SHALL give the
gate's own output to the agent that wrote the work, in the same worktree, and
attempt the commit again after it responds. The output SHALL name what the gate
said, not a summary of it, because the file, line and rule are the actionable
part.

#### Scenario: A lint rule the author can fix

- **WHEN** the gate rejects a commit over a rule violation that does not fix
  itself
- **THEN** the agent is shown that output, fixes the violation in place, and the
  commit is made

#### Scenario: What the fix round is for

- **WHEN** the agent is asked to satisfy a gate
- **THEN** it is asked to make the existing work pass, not to reconsider the work

### Requirement: The rounds are bounded and the reason is recorded

The pipeline SHALL attempt this a small, fixed number of times and then fail the
unit as it does today. The gate's last output SHALL be recorded on the unit, so
the reason is visible where a unit's state is read rather than only in a log.

#### Scenario: A gate that cannot be satisfied

- **WHEN** the gate still rejects the commit after the last attempt
- **THEN** the unit fails, and its record carries the gate's final output

### Requirement: The gate is never bypassed

The pipeline SHALL NOT commit with the gate disabled, skipped, or limited to a
subset of files chosen to avoid it, under any circumstance — including the last
attempt before failing.

#### Scenario: The tempting shortcut

- **WHEN** a commit cannot be made to pass the gate
- **THEN** no commit is made at all, rather than one that skipped verification
