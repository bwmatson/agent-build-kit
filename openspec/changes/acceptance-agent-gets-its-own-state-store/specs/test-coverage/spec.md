## ADDED Requirements

### Requirement: An acceptance test gives the agent a store of its own and proves its sessions are kept

The acceptance tests that start a real agent below the test process SHALL give it, when the workspace configures
it, a scratch home: a temporary directory made fresh for the test module, readable by its owner only, holding
symbolic links to exactly the files the workspace lists from the person's real home for that agent, and nothing
else. The names of the variable the agent reads for its home, of the real home and of the files SHALL be read from
the environment, set from the workspace's `verify.env`, and the framework SHALL name no agent. The scratch home's
variable SHALL be added to the environment of every process the test starts that may start the agent, and the test
SHALL NOT use the real home as the agent's home, and SHALL NOT link a directory or the agent's state database.
When the variable naming the agent's home is unset, nothing SHALL change. A test that later resumes a session
SHALL, after the first agent step, check that the agent lists the recorded session for its working directory, and
SHALL fail there, with a message that names a missing session store and the variables to check, when it does not.

#### Scenario: The scratch home holds exactly the listed links

- **GIVEN** the three variables set and a real home holding the listed files
- **WHEN** the helper builds the agent's home
- **THEN** it is a new directory readable by its owner only, holds one symbolic link per listed name pointing at
  the real file and nothing else, and the environment it returns sets the named variable to it and nothing more

#### Scenario: The real home is never used

- **GIVEN** a real home that is, or contains, the scratch directory
- **WHEN** the helper builds the agent's home
- **THEN** it fails and the test does not start the agent

#### Scenario: An unset variable changes nothing

- **GIVEN** the variable naming the agent's home is unset
- **WHEN** the helper runs
- **THEN** no directory is created and the environment it returns is empty

#### Scenario: A missing linked file fails clearly

- **GIVEN** a listed name that is absent from the real home
- **WHEN** the helper builds the agent's home
- **THEN** it fails naming the file and the real home, and a name that is a directory or the state database is
  refused

#### Scenario: The environment reaches the process that starts the agent

- **GIVEN** the helper's environment added to the one the fixture hands `abk tick`
- **WHEN** the tick process starts the agent command
- **THEN** the agent sees the scratch path in the named variable

#### Scenario: A session that is not listed fails at the first step

- **GIVEN** the first agent step of a test that later resumes a session, and an agent that lists no session for
  its working directory
- **WHEN** the precondition runs
- **THEN** the test fails there, naming the session, the working directory, the missing session store and the
  variables to check

#### Scenario: A listed session passes

- **GIVEN** an agent that lists the recorded session for its working directory
- **WHEN** the precondition runs
- **THEN** it passes and the test goes on to resume it

#### Scenario: A refused resume says why

- **GIVEN** an agent that does not list the session a run asks to resume
- **WHEN** the runtime refuses the resume
- **THEN** the run log says how many sessions the agent listed for that directory and whether a process above it
  has `pytest` in its argv, and the resume decision is as before
