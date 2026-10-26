## ADDED Requirements

### Requirement: An agent node records that its run has started

Each node that runs an agent SHALL record its own name in the unit's thread state before its agent
starts, independently of whether the runtime reports a session, and SHALL clear it when the node
completes, so that a killed run leaves it behind.

#### Scenario: A kill before the agent reports a session

- **GIVEN** a node killed after it started but before its agent named a session
- **WHEN** the thread is inspected
- **THEN** the node's name is still recorded

#### Scenario: A node that completes

- **WHEN** a node completes
- **THEN** its record is cleared

### Requirement: A node killed during an agent run resumes over the work its agent left

When a node that runs an agent is re-run after its run was killed, meaning its recorded start
names it and no live process holds the unit's branch, uncommitted changes in the unit's
worktree SHALL be taken as that node's own and SHALL NOT make the resume fail. When the node
continues its recorded session, the agent SHALL be given nothing beyond the interruption prompt.
When the node starts a new session over such changes, its prompt SHALL name the changed paths and
say they are uncommitted work from an interrupted run of the same step, to be reviewed, kept where
right, and finished, and SHALL NOT tell the agent to discard them. The node's own commit SHALL
include them, and no separate work-in-progress commit SHALL be made.

#### Scenario: A killed rework with a recorded session

- **GIVEN** a rework killed mid-edit, leaving an uncommitted file, with its session recorded
- **WHEN** the thread is resumed and the session continues
- **THEN** the unit goes on to review and the file is in the rework's commit
- **AND** the agent was given no list of leftovers

#### Scenario: A killed implement with no session

- **GIVEN** an implement node killed before its session was recorded, leaving uncommitted code
- **WHEN** it is resumed in a new session
- **THEN** its prompt names the changed paths and calls them uncommitted work from an interrupted run
- **AND** the file is still in the worktree

#### Scenario: A session that cannot be resumed

- **GIVEN** a recorded session the runtime cannot continue
- **WHEN** the node falls back to a new session
- **THEN** the prompt carries the leftover note

#### Scenario: Killed by a limit or a timeout

- **WHEN** a rate limit or a timeout kills an agent mid-run
- **THEN** the resume behaves the same way

### Requirement: Uncommitted work that is not a node's own parks the unit

When the worktree has uncommitted changes and no recorded start names the node being run, or a live
process holds the unit's branch, the unit SHALL be held with the cause `dirty_worktree`, the changed paths and a request that
a person commit or remove them, SHALL NOT be failed, and nothing SHALL be cleaned automatically. A
requeue after the tree is clean SHALL resume it, and the status SHALL list such units with their
reason.

#### Scenario: A hand edit

- **GIVEN** a unit that was not killed and whose worktree a person edited
- **WHEN** a node asks for the worktree
- **THEN** the unit is held with the paths and the request, not failed

#### Scenario: A non-agent node

- **GIVEN** a dirty tree at a node that does not run an agent
- **WHEN** it is resumed
- **THEN** the unit is held, not failed

#### Scenario: An agent node reached but never started

- **GIVEN** a unit waiting at an agent node for the usage window, with a person's edit in its tree
- **WHEN** the node is next run
- **THEN** the unit is held, because no start was recorded

#### Scenario: A runtime that reports no session

- **GIVEN** a node killed mid-edit on a runtime that names no session
- **WHEN** it is resumed
- **THEN** it resumes over the leftovers in a new session, because its start was recorded

#### Scenario: After the tree is cleaned

- **WHEN** a person cleans the tree and requeues the unit
- **THEN** it resumes at the node
