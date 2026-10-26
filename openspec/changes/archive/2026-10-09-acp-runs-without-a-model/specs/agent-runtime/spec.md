## ADDED Requirements

### Requirement: Every node runs on a runtime that names no models

A runtime that declares no model names SHALL run every node that runs an agent. The run entry point SHALL accept a call with
no model, SHALL pass an empty model to the runtime, and the runtime SHALL select no model.

#### Scenario: Writing the tests on the ACP runtime

- **GIVEN** the ACP runtime with every role empty
- **WHEN** a unit's tests node runs
- **THEN** the agent starts, and no model is selected

#### Scenario: Every agent node

- **GIVEN** the same runtime
- **WHEN** the nodes that implement, fix checks, rework and adapt run, and a session is continued
- **THEN** each reaches the runtime with no model, and none fails before the agent starts

#### Scenario: A runtime that names its models

- **GIVEN** the Claude Code runtime with its default models
- **WHEN** a node runs
- **THEN** it runs on the model for its role as before
