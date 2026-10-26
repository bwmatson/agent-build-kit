# test-determinism Specification

## Purpose
TBD - created by archiving change tier2-tests-have-their-own-time-limit. Update Purpose after archive.

## Requirements

### Requirement: A tier-2 test runs under its own time limit

A test that carries the tier-2 marker SHALL run under a time limit of its own, thirty minutes by default and set by its own option, with zero
turning it off, on each of its setup, call and teardown; every other test SHALL keep the limit it has. A failure from either limit SHALL
name the limit that was passed and say which kind it was. The limit on a tier-2 test SHALL NOT change the pipeline's tier-2 command, its
environment or the result it posts.

#### Scenario: A live test that takes minutes

- **GIVEN** a test with the tier-2 marker that runs for five minutes
- **WHEN** it runs under the default limits
- **THEN** it is not failed by the limit

#### Scenario: A module fixture that runs a tick

- **GIVEN** a module-scoped fixture of tier-2 tests that takes five minutes in its setup
- **WHEN** the first of those tests starts
- **THEN** its setup is not failed by the fast limit

#### Scenario: A tier-2 test that hangs

- **GIVEN** a tier-2 test that does not return
- **WHEN** the tier-2 limit passes
- **THEN** it fails with a message naming the tier-2 limit and its length

#### Scenario: A fast test is unchanged

- **GIVEN** a test without the tier-2 marker that does not return
- **WHEN** the fast limit passes
- **THEN** it fails with the message it had before

#### Scenario: The limit turned off

- **WHEN** the tier-2 limit is set to zero
- **THEN** a tier-2 test is not limited and the fast limit is as before

### Requirement: `tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: `tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_still_stops_new_builds_for_the_pass` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: `tests/runtimes/test_acp_outcome.py::test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: `tests/replay/test_replay_proxy_edges.py::test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: `tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_ends_at_its_deadline_within_the_pass` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: An e2e-test test may start a real agent

The guards of the suite that refuse a real agent process, the runtime's spawn and a direct start of `claude`, SHALL NOT
apply to a test that carries the tier-2 marker, on the test, its class or its module, and SHALL apply to every other test
as they do now. The guards on refreshing the login, reading the usage window, running `gh` and reaching the code host SHALL
apply to every test, e2e-test included, and an e2e-test test that reaches one SHALL fail with that guard's message.

#### Scenario: A test without the marker is refused

- **GIVEN** a test that carries no tier marker and starts the runtime's real agent
- **WHEN** it runs
- **THEN** it fails with the message that names the injection it should use

#### Scenario: An e2e-test test is not refused

- **GIVEN** a test marked `local_stack` that starts a harmless program through the runtime's real spawn
- **WHEN** it runs
- **THEN** the program runs and no guard refuses it

#### Scenario: The marker on the module counts

- **GIVEN** a module whose tests are all marked `local_stack` through a module-level mark
- **WHEN** one of them starts the real spawn
- **THEN** it is not refused

#### Scenario: The direct start follows the same rule

- **GIVEN** a test marked `local_stack` and one without the marker, each starting a program whose name is `claude`
- **WHEN** they run
- **THEN** the first is not refused by the guard and the second is, with the guard's message

#### Scenario: The other guards hold for an e2e-test test

- **GIVEN** a test marked `local_stack` that refreshes the login, reads the usage window, runs `gh` or calls the code host
- **WHEN** it runs
- **THEN** it fails with that guard's message

### Requirement: `tests/runtimes/test_policy_agent_harness.py::test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

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

### Requirement: The suite starts no process by forking a multi-threaded one

A test that starts a process SHALL NOT do so by forking the test runner's process: the `fork` start method SHALL NOT be used by a test, and a test that
needs processes of its own SHALL start them with `spawn` (or as a `subprocess`), from a function in a module the child can import by name, with whatever the
child needs passed to it or rebuilt there and not inherited from the parent's patches. The pytest options SHALL turn the `DeprecationWarning` that Python
raises for forking a multi-threaded process into an error, so a test that does so fails at that line. A test that checks a property between
processes SHALL keep that property and its assertions, and SHALL give the same result run serially and under the parallel runner.

#### Scenario: Processes contend for a file lock while the runner has threads

- **GIVEN** a test that starts several processes which ask for the same cached reading, with another thread alive in the test's own process
- **WHEN** it runs
- **THEN** it starts the processes without the multi-threaded-fork warning, and exactly one call is made to the faked endpoint

#### Scenario: The children rebuild what the parent patched

- **GIVEN** a parent that replaced the endpoint and the credential paths for the test
- **WHEN** a spawned child asks for the reading
- **THEN** it reaches the same faked endpoint and the same cache file, not the real endpoint or the machine's own files

#### Scenario: A fork of a multi-threaded process fails the test

- **GIVEN** the pytest options of the repository
- **WHEN** a test forks a process while another thread is alive
- **THEN** the test fails with the multi-threaded-fork warning raised as an error

#### Scenario: Other warnings are unchanged

- **GIVEN** a test that raises a `DeprecationWarning` of any other message
- **WHEN** it runs
- **THEN** it is reported in the warnings summary as before and is not failed by the filter

#### Scenario: The filter is configured

- **WHEN** the repository's `[tool.pytest.ini_options]` is read
- **THEN** it holds the entry that turns the multi-threaded-fork warning into an error

### Requirement: `tests/cli/test_tick_scheduling.py::test_stopping_still_awaits_the_builds_in_flight` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: `tests/runtimes/test_policy_agent_harness.py::test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: `tests/pipeline/test_moved_base_run_stored.py::test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: `tests/cli/test_tick_scheduling_projects.py::test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time

### Requirement: `tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
