## ADDED Requirements

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
