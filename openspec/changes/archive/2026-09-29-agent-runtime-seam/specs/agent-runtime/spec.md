# Spec Delta

## Purpose

Defines how the pipeline reaches an agent: one seam every call goes through,
how a workspace selects which agent executes its work, and that selecting the
default changes nothing about how the pipeline behaves.

## ADDED Requirements

### Requirement: One seam for every agent call

Every step that runs an agent and reads its answer — build, rework, review,
rework review, the planner's graph call, conflict resolution, a track phase,
research, propose — SHALL reach it through one runtime interface, given a
request expressed in the pipeline's own terms (a role, a working directory,
readable directories, a tool policy) rather than one agent's command-line
flags. The interface SHALL report a refusal, a rate limit and an interruption
as distinct outcomes, so that every call site interprets them the same way.

#### Scenario: A step that today has no refusal handling

- **WHEN** conflict resolution is run and the agent refuses because a usage
  window is spent
- **THEN** the step reports a rate limit rather than reporting that the agent
  produced no changes

#### Scenario: A step that today has its own executor

- **WHEN** the planner's graph call runs
- **THEN** it goes through the same interface, with the same refusal
  interpretation, as a build run

#### Scenario: Every call site is testable at the seam

- **WHEN** a test supplies its own runtime
- **THEN** every step, including the scheduled tracks and conflict resolution,
  uses it without a module attribute being replaced

### Requirement: A workspace selects its runtime, and may override it per machine

`abk.yaml` SHALL name the runtime that executes every step for the whole
workspace, defaulting to the current one so an existing file needs no edit. An
environment variable SHALL override that selection for one machine or one
invocation, so a runtime can be tried without changing the committed setting
for every repo. A runtime that needs a fact the framework cannot default SHALL
take it from an optional per-runtime entry, and a workspace using a runtime
that needs none SHALL NOT have to write that entry at all.

#### Scenario: An existing installation

- **WHEN** an `abk.yaml` written before this change is loaded
- **THEN** it loads unchanged, the runtime is the current one, and the existing
  models block still names that runtime's models

#### Scenario: Trying a runtime out

- **WHEN** the override names a different runtime for one invocation
- **THEN** that invocation uses it and the committed selection is untouched

#### Scenario: A selection that cannot work

- **WHEN** the selected runtime is unknown, or needs a fact its entry does not
  supply
- **THEN** loading the configuration fails with a message naming what is
  missing, rather than every unit being held later

### Requirement: Model names are resolved per runtime

A role's model SHALL be resolved against the active runtime: the workspace's
model block, then that runtime's own overrides where present, then the
per-machine overrides. A role no configuration names SHALL fall back to the
active runtime's own default, never to another runtime's.

#### Scenario: Two runtimes whose model names differ

- **WHEN** a workspace declares model names for a second runtime and selects it
- **THEN** those names are used, and the first runtime's names are not sent to it

### Requirement: Usage limits are a runtime capability, not an assumption

A runtime SHALL declare whether it has an account-level usage window at all.
Where it does, today's rule stands: an unknown reading pauses. Where it does
not — an agent billed on demand, with no ceiling over a time window — the
usage check SHALL be skipped entirely rather than treated as an unknown
reading, and a run SHALL be limited only by the work it has to do.

#### Scenario: A runtime with no usage window

- **WHEN** units are started under a runtime billed on demand
- **THEN** no usage reading is attempted, nothing pauses for want of one, and
  the pause threshold has no effect

#### Scenario: A runtime with a usage window

- **WHEN** a reading cannot be obtained under the current runtime
- **THEN** the pipeline pauses, as it does today

### Requirement: Selecting the default runtime changes nothing observable

With the default runtime selected, every step SHALL invoke the agent exactly as
before this change: the same binary, the same flags, the same per-run policy
hook registration, the same streamed progress, and the same usage semantics.

#### Scenario: The argv the pipeline builds

- **WHEN** a build, review, rework, track phase, research or proposal run is
  constructed
- **THEN** the command it would execute is identical to the one built before
  this change, including the hook registration and the denied commands
