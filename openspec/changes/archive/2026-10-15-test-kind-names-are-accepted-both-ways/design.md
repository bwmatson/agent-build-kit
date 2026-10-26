# Design

## Context

"Tier 1" and "tier 2" are strings compared in many places and the values of a unit's `tier` field in the store. The heading parser
accepts exactly the two, `abk.yaml` keys carry the names (`tier1_*`, `tier2_*`, `tests.tier2_marker`, `tier2_runtimes`,
`tier2_splits`), and `planned.json` and `units.json` hold the old values.

## Decisions

- **The enum carries the new strings.** `TestTier.UNIT_TEST = "unit-test"` and `TestTier.E2E_TEST = "e2e-test"`: the tagged and stored
  value is the same string, and the `-test` suffix keeps the tag apart from "unit" meaning a pull request's worth of task groups.
- **One compatibility module.** A table of old to new for tags, settings keys, stored values, state-file names and metric names, and
  the notice text. Reading goes through it and writing never does. This change creates the module and wires the three edges; the
  rename later makes every other module import the new names, and the guard that bans the old names elsewhere arrives with the last
  slice of that change.
- **The old spelling is a notice, not an error,** for one release, from the four commands that report configuration and planning
  problems. A file that holds an old and a new spelling of the same setting is an error naming both, since the intent is unclear.
- **Stored values** are read with either spelling and rewritten with the new one the next time the file is written. The `tier` field
  keeps its stored key name until the rename slices rename its readers, and both keys are read.
- **Nothing in this change renames a module, a class or a setting's internal name.** That is the next change, built on top of this one.
  Waiting units are made to depend on this layer so they are built with the new names available and a notice for the old.

## Risks

- **A spelling the table misses.** The next change's guard finds it, since it searches the whole tree for every spelling the table lists.
- **Notice noise.** One notice per old spelling and place, so a file with many old tags says so once per tag; the notice names the
  command that moves them when it exists.
