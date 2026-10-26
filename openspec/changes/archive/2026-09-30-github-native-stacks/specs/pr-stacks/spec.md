# Spec Delta

## Purpose

Defines how the chain of pull requests the pipeline already builds is registered
as a stack the code host knows about, and what the pipeline must tolerate once
the host has an opinion about those branches.

## ADDED Requirements

### Requirement: A code host declares whether it has stacks

A forge SHALL declare whether the host supports first-class stacks, the way it
already declares other host behaviour the pipeline must not assume. Every
behaviour in this specification SHALL apply only where that is true, and a host
without stacks SHALL behave exactly as before.

#### Scenario: A host without stacks

- **WHEN** a unit's pull request is opened on a host that does not support stacks
- **THEN** nothing is registered, and the pull request and its body are as they
  are today

### Requirement: A chain of pull requests is registered as a stack

When a unit's pull request is opened against another unit's branch, the pipeline
SHALL tell the host that the two are one series, ordered from the bottom, and
SHALL extend that series as each later unit of the chain opens its own pull
request. The pipeline SHALL determine whether a series already exists by asking
the host which stack the base pull request belongs to, rather than by
remembering.

#### Scenario: The second pull request of a chain

- **WHEN** a unit's pull request is opened against a unit whose pull request is
  in no stack
- **THEN** a stack is created containing both, bottom first

#### Scenario: A third and later unit

- **WHEN** a unit's pull request is opened against a unit already in a stack
- **THEN** it is appended to that stack

#### Scenario: A stack whose pull requests have all merged

- **WHEN** the base pull request belongs to a stack that can no longer be
  extended
- **THEN** a new stack is started rather than the failure being reported as one

#### Scenario: Another request is changing the same stack

- **WHEN** registration is refused because the stack is being modified
  concurrently
- **THEN** it is retried, since overlapping ticks make that ordinary

### Requirement: Registration never costs a unit

Registering a stack SHALL happen only after the pull request exists, and its
failure SHALL NOT fail, hold or delay the unit. A refusal SHALL be recorded on
the unit and logged once, and the unit SHALL proceed exactly as it would on a
host without stacks. No later step SHALL require a stack to exist.

#### Scenario: The host refuses

- **WHEN** the host rejects the registration for any reason — the feature
  unavailable, the repository ineligible, the chain not accepted
- **THEN** the unit continues, its pull request is unaffected, and the reason is
  on its record

#### Scenario: Nothing depends on it

- **WHEN** a stack was never registered for a chain
- **THEN** building, reviewing, rebasing and merging behave as they do today

### Requirement: The pipeline tolerates the host rebasing its branches

The pipeline SHALL NOT assume it is the only writer of a unit's branch. Where the
host rebases and re-targets the pull requests above a merged one, a branch's head
may differ from the commit review approved without any run having changed it, and
the pipeline SHALL establish that by inspecting the branch and the recorded
approval rather than by inferring it from what it last did.

#### Scenario: The host moved a branch after a stack merge

- **WHEN** a unit's branch head no longer matches the commit review approved, and
  no run of that unit caused it
- **THEN** the unit is re-reviewed before anything is pushed, as any other
  unapproved head would be, and nothing is merged on the strength of the old
  approval

### Requirement: The pull request says what the host does not show

Where the host renders the series, the pull request body SHALL NOT restate the
unit's position or what lies beneath it. It SHALL instead report what the host
cannot: whether the chain is linear — since a non-linear one cannot be merged
until it is rebased — and what the pipeline is waiting for. Where the host has no
stacks, the body SHALL keep describing the chain as it does today.

#### Scenario: A linear chain on a host with stacks

- **WHEN** the body is written for a unit in a registered stack
- **THEN** it does not repeat the ordering the host shows, and says the chain is
  linear

#### Scenario: A chain the pipeline has left non-linear

- **WHEN** a chain cannot be merged until it is rebased
- **THEN** the body says so, rather than leaving a reviewer to infer it from a
  disabled control
