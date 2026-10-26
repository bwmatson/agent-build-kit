# Proposal

## Why

The ACP runtime declares no model names: every role is empty, so the agent runs on its own default. The nodes that write
tests, implement, fix checks and rework pass the model to the run entry point only when it is not empty, and the entry
point, since it took over from two others, requires one. So for a runtime with no model names every such node fails at once
with a missing argument, before the agent starts, and no unit can be built through it. Nothing in the fast tests runs a node
with an empty model, and the live tests that would are run only when a change is verified, so it was not seen until a
change's live tests ran after it.

## What Changes

- **The run entry point accepts no model:** an empty model means the runtime's own default, as the runtime already reads it.
- **Every node runs with an empty model:** a test builds each node with a runtime that names no models and checks the run
  reaches the runtime with no model selected.

## Impact

- agent-build-kit: the run entry point's signature and one test. No change for a runtime that names its models.
