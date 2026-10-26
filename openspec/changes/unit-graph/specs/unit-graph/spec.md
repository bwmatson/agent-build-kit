# Spec Delta

## Purpose

Defines how a unit's lifecycle runs: as a checkpointed graph, one thread per
unit, that waits for people and the forge without holding anything, and that
resumes exactly where it stopped.

## ADDED Requirements

### Requirement: A unit runs as one checkpointed thread

Each unit SHALL run as one LangGraph thread whose identifier is the unit's id.
The thread SHALL be checkpointed after every node, written before the next
node starts, in a store in the installation's state directory. A thread SHALL
exist from the unit's first start until the unit merges, is closed or is
satisfied, and SHALL be deleted then.

#### Scenario: The process dies mid-node

- **WHEN** the tick process is killed while a node runs
- **THEN** the next tick resumes the thread at that node, and the node does
  not repeat what its earlier run already committed, pushed or opened

#### Scenario: A unit finishes

- **WHEN** a unit merges, is closed or is satisfied
- **THEN** its thread no longer exists

### Requirement: The lifecycle is the graph's nodes and edges

A unit's steps — preparing its branch, tests, implementation, review and
rework, adapting onto a moved base, the test tiers, the fresh-base check,
pushing, opening its pull request — SHALL each be a node, and which step
follows SHALL be decided by the graph's edges, not by a recorded step name.
The nodes SHALL use the same agent, git and forge operations the pipeline
uses today, and the outcomes they reach SHALL be the ones the pipeline reaches
today for the same inputs.

#### Scenario: The scenarios the old engine passed

- **WHEN** the scenarios the step runner was tested against are run against
  the graph
- **THEN** each reaches the same outcome, state and pull request as before

### Requirement: Waiting holds nothing

A unit waiting for review, for a person, or for the usage window SHALL wait in
an interrupt of its thread, holding no branch lock and no repo turn, and
taking no slot from `max_concurrent_stacks`.

#### Scenario: A unit in review for days

- **WHEN** a unit has waited in review for days and an event about it arrives
- **THEN** the event is delivered without waiting for any lock the unit holds

### Requirement: Events reach a unit only by resuming its thread

The poller's events about a unit, and `abk requeue`, SHALL reach the unit as a
resume command on its thread — rework with its reason and feedback, a moved
base, a hold, a merge, a close, a requeue — and SHALL NOT change the unit's
in-run progress any other way. An event for a unit whose thread is in the
middle of a node SHALL be delivered when that node returns.

#### Scenario: A comment on a unit in review

- **WHEN** a new review comment arrives for a unit waiting in review
- **THEN** its thread resumes into rework with the comment as feedback

#### Scenario: An event during a node

- **WHEN** a merge conflict is reported while the unit's review node runs
- **THEN** the event is delivered after that node returns, not lost

### Requirement: A usage pause is an interrupt at a node boundary

Before an agent step, a node SHALL ask the usage guard, and when refused SHALL
interrupt the thread with the reason and the guard's resume time. The tick
SHALL resume such threads when the guard allows. A node already running SHALL
NOT be interrupted for usage.

#### Scenario: The window clears

- **WHEN** a thread interrupted for usage is checked on a tick where the guard
  allows
- **THEN** it resumes at the node it stopped before

### Requirement: Checkpoints load only known types

Checkpoint deserialisation SHALL be restricted to an explicit list of the
state's types, and a checkpoint holding every type the state uses SHALL load.

#### Scenario: A type left off the list

- **WHEN** the state gains a type not on the allowlist
- **THEN** a test fails, rather than a resume in production

### Requirement: A killed agent step continues its session where it can

An agent node SHALL record the agent's session id in the unit's thread state
once the runtime reports it. When the process is killed during the node and the
thread is resumed, the node SHALL resume that session where its runtime
supports it, telling the agent that the process was interrupted and that it must
re-read the worktree before relying on its memory. Where the session cannot be
resumed, the node SHALL run from its start in a new session and the run log
SHALL say so. A recorded session id SHALL NOT be used by another node or
another unit.

#### Scenario: A power loss mid-implementation

- **GIVEN** an agent node that recorded its session id and was killed partway
- **WHEN** the next tick resumes the thread
- **THEN** the node resumes that session with the interruption note
- **AND** the unit is not requeued to `planned`

#### Scenario: The session cannot be resumed

- **GIVEN** a recorded session id the runtime refuses to load
- **WHEN** the thread is resumed
- **THEN** the node runs from its start in a new session
- **AND** the run log says the session could not be resumed
