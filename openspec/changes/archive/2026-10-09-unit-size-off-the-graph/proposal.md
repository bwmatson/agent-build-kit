# Proposal

## Why

The graph page shows how units depend on one another and where each stands. A unit that landed over its size ceiling carries
a line of its own on its node, saying how many lines it landed and that this was over the ceiling. That is a measure of how a
unit was sized and how well its estimate held, not of where it is in the graph, and it makes a merged unit look unfinished
long after it merged. The measure matters and keeps its places: the unit's log and the status command's list.

## What Changes

- **The graph page no longer marks a unit over the ceiling:** a node shows its tier, state and pull request, as it does for a
  unit under the ceiling.
- **The size is still recorded, logged and listed:** the actual lines stay on the unit, a unit over the ceiling is logged when
  its pull request is opened or updated, and the status command lists it.

## Impact

- agent-build-kit: the graph page's node label, one requirement, the architecture document and the changelog.
