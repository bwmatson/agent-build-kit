# Spec Delta

## Purpose

Defines that the pipeline's forbidden commands stay forbidden whichever agent
executes them, that the pipeline proves this rather than assuming it, and how
an operator is told and offered a fix.

## ADDED Requirements

### Requirement: A runtime declares how much of an agent's work the pipeline can interpose on

Each runtime SHALL declare whether every tool call reaches the pipeline before
it runs, whether only the calls the agent chooses to ask about do, or whether
none do. The command rules themselves SHALL stay owned by the pipeline and
independent of any agent, so the same rules apply however they are delivered.

#### Scenario: Reporting the current runtime's coverage

- **WHEN** the installation is checked
- **THEN** the active runtime's coverage is reported, and anything less than
  every call is called out rather than left implicit

### Requirement: The pipeline proves the forbidden commands are refused

The pipeline SHALL be able to ask the active runtime whether each class of
command it forbids — merging a pull request, amending a commit, pushing to a
default branch, writing outside the unit's worktree, writing into the planning
repo's specs directory — is actually refused on this machine, and SHALL report
which classes are not. A runtime that can answer without calling an agent
SHALL do so.

#### Scenario: A runtime whose enforcement is built in

- **WHEN** the check runs under a runtime that registers the pipeline's own
  policy before each tool call
- **THEN** it reports every class enforced, without spending an agent call

#### Scenario: A class that is not refused

- **WHEN** the check finds that a forbidden class would run
- **THEN** it names that class in the pipeline's own words, not the agent's

### Requirement: Setup asks before changing an agent's configuration

`abk doctor` SHALL fail, not warn, when a forbidden class is unenforced, and
SHALL print the command that would fix it. `abk init` SHALL report the same
finding and SHALL ask for confirmation before running that command, which the
installation supplies; declining SHALL leave everything unchanged and say which
guarantee is missing. The framework SHALL NOT edit another tool's
configuration itself.

#### Scenario: Setup finds an unconstrained agent

- **WHEN** `abk init` runs and a forbidden class is unenforced
- **THEN** it reports the class, asks before running the installation's fix
  command, and runs it only on confirmation

#### Scenario: The operator declines

- **WHEN** the operator declines the fix
- **THEN** nothing is changed and the missing guarantee is stated

#### Scenario: A check that costs an agent call

- **WHEN** the check has to ask an agent, and is run repeatedly
- **THEN** its result is reused for a short period rather than re-run every time
