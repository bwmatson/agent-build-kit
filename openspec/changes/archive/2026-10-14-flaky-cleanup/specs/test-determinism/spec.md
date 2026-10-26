## ADDED Requirements

### Requirement: Existing timing hazards are removed and leave the allowlist

Each test that relied on a sleep to order actors, on a polling loop written with a sleep, on a copy of the shared wait
helper, or on a server thread nothing joins SHALL be rewritten to signal, wait through the shared wait helper, count what
it waited for, or shut the thread down, SHALL assert what it asserted before, and its file SHALL be removed from the
guard's allowlist in the same change that removes the last hazard from it. An allowlisted file that no longer holds a
hazard SHALL fail the guard.

#### Scenario: Two holders of a lock

- **GIVEN** a test of two concurrent holders of a lock
- **WHEN** it runs
- **THEN** the second waits on a signal that the first holds the lock, its own wait notice shows that it blocked, and no sleep decides the order

#### Scenario: A subprocess test waits on an event

- **GIVEN** a test that waits for a child process to reach a point
- **WHEN** it runs
- **THEN** it waits through the shared wait helper on a condition the child makes true and does not sleep in a loop

#### Scenario: Several refreshes

- **GIVEN** a tick test that must see that a unit is not readmitted over several refreshes
- **WHEN** it runs
- **THEN** it waits until a counted number of refreshes has run and does not sleep for a fixed time

#### Scenario: A fake server's thread

- **WHEN** a test starts a fake server on a thread
- **THEN** it shuts the server down and joins the thread in the function that started it

#### Scenario: The allowlist shrinks

- **WHEN** a group removes the last hazard from a file
- **THEN** the file is removed from the allowlist and the guard fails if a hazard returns to it or if the file stays listed without one
