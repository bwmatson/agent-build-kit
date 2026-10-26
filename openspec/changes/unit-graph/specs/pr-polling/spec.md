# Spec Delta

## Purpose

Changes what the pull request poller's events do once a unit runs as a graph
thread.

## ADDED Requirements

### Requirement: A poller event resumes the unit's thread

An event the poller raises for a unit — rework requested, a merge, a close, a
hold, a moved base — SHALL be delivered as a resume command on that unit's
thread, and SHALL change the scheduling record (state, pull request, history)
only as the thread's nodes do. An event that cannot be delivered yet, because a
node of that thread is running, SHALL be kept and reported again.

#### Scenario: A failing check

- **WHEN** a check starts failing on a unit's pull request
- **THEN** the unit's thread resumes into rework with the check's output as
  feedback
