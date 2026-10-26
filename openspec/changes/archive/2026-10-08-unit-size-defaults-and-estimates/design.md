# Design

## Defaults

`LimitsConfig.min_unit_lines = 400`, `max_unit_lines = 750`; the validator that the ceiling
exceeds the floor is unchanged. `docs/configuration.md` and the `abk-config` skill show the
new values. The planner prompt already takes both from the configuration, so no prompt text
changes for the numbers.

## The estimate's definition

The planner prompt's estimate paragraph is replaced by: additions plus deletions in every
file the groups change (code, tests, docs, fixtures, the changelog), excluding generated
files such as lockfiles; for a group that removes or rewrites code, count the removed lines
too; when unsure, estimate high. A test pins the sentence so the prompt cannot lose it.

## Actual size

`StoredUnit.actual_lines: int | None`. Set where the pull request is opened and where a
rework's push updates it, from the host's own totals for the pull request (the forge's
additions and deletions) less lines in generated files (a configurable list of path
patterns defaulting to lockfiles). It is overwritten on each push, so it is the size the
reviewer sees. Absent for a unit with no pull request.

## Visibility

When `actual_lines > max_unit_lines` the unit's log records "estimated N, landed M, over the
ceiling of C"; the graph page marks the unit; `abk status` lists units over the ceiling. The
planner is not re-run and nothing blocks the unit.

## Out of scope

Enforcing the ceiling against the branch, splitting a unit that grew, and changing the
planner's model.
