# Proposal

## Why

Recent pull requests have been larger than the unit ceiling. The estimate has not stopped
working: it never measured anything. The planner is asked for `estimated_lines` (additions
plus deletions, excluding lockfiles) and the ceiling is enforced against that guess only;
the configuration comment says so: a branch is not measured against it, so a unit can still
land larger. Measured on 24 recent units, actual size (additions plus deletions of the pull
request) against the estimate had a median ratio of 1.3, with a long tail:

- most units landed 1.0 to 1.3 times their estimate;
- units that wrote a lot of tests, docs and fixtures beside the code landed 2 to 3.5 times;
- units that removed or rewrote existing code landed 6 to 12 times, because the deleted
  lines count and the estimate was of the new code.

Nothing records the actual size next to the estimate, so none of this is visible to the
pipeline, and the planner is never corrected.

## What Changes

- **Defaults:** the floor is 400 and the ceiling 750 changed lines (from 500 and 1000), in
  the configuration, its documentation and the config skill. A workspace that sets either
  keeps its value.
- **The planner is told what an estimate counts:** additions and deletions across code,
  tests, docs, fixtures and the changelog, excluding generated files such as lockfiles; a
  group that removes or rewrites existing code is estimated by the lines it removes as well
  as the lines it adds; and when unsure it estimates high.
- **The actual size is recorded:** when a unit's pull request is opened, and again when it
  is pushed after a rework, the unit records its actual changed lines (additions plus
  deletions, excluding generated files) beside its estimate.
- **The difference is visible:** a unit whose actual size exceeds the ceiling is logged and
  marked in the graph page and in `abk status`, and `abk report` (when present) shows
  estimated against actual per unit. The ceiling still shapes plans; this change does not
  block a unit from landing larger.
