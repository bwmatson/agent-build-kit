## ADDED Requirements

### Requirement: An agent keeps long command output in an ignored scratch file and reads from it

The prompts of the agents that build, rework and resolve conflicts SHALL tell them to run
a command whose output may be long or slow to produce with its output written to a file in
a per-run scratch folder, and to read what they need from that file, and SHALL tell them
not to run a command again only to see different lines of its output. The scratch folder
SHALL be inside the unit's worktree, SHALL belong to that one agent run, SHALL be excluded from git through the worktree's local
exclude file so no add or commit by an agent or by the pipeline can include it, and SHALL
be removed when the run ends. The command policy SHALL allow writing to that folder by
redirection and SHALL still refuse shell writes elsewhere.

#### Scenario: A full test run

- **WHEN** an agent runs the test suite
- **THEN** its prompt told it to write the output and exit status to the scratch folder and
  read the summary from there

#### Scenario: The summary was cut off

- **GIVEN** an agent that needs more of a run's output than it read
- **WHEN** it needs the failing test's details
- **THEN** it reads them from the file and does not rerun the suite

#### Scenario: The folder cannot be committed

- **GIVEN** files in the scratch folder
- **WHEN** an agent runs `git add -A` or the pipeline commits leftovers
- **THEN** nothing from the folder is staged or committed

#### Scenario: A redirect elsewhere

- **WHEN** an agent redirects a command's output into a tracked file
- **THEN** the policy refuses it as before

#### Scenario: A run ends

- **WHEN** an agent run ends in any outcome
- **THEN** its scratch folder is removed

### Requirement: Agents do not share command output

Each agent SHALL run the commands it needs itself and read only its own scratch files.
The pipeline SHALL NOT give one agent another agent's command output, and SHALL NOT use an
agent's command output in place of running a check itself.

#### Scenario: A review after a build

- **GIVEN** a builder that ran the suite and wrote its output to its scratch folder
- **WHEN** the unit is reviewed
- **THEN** the reviewer's run has an empty scratch folder of its own and its prompt tells it
  to run its own commands

#### Scenario: Tier 1 after an agent's run

- **GIVEN** an agent whose own suite run passed
- **WHEN** tier 1 runs
- **THEN** it runs the suite itself

### Requirement: The suite runs once per round, per agent

The prompts SHALL tell an agent to run the full test suite once after the round's last
edit, to read its result from the scratch file, and after a fix to run only the tests that
failed.

#### Scenario: A fix after a failed run

- **GIVEN** a suite run with two failing tests
- **WHEN** the agent fixes them
- **THEN** its prompt told it to run those tests and not the whole suite again
