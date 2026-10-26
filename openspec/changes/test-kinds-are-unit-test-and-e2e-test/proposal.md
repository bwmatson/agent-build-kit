# Proposal

## Why

abk calls its two kinds of test "unit-test" (lint, types and the ordinary suite, run anywhere) and "e2e-test" (the real local stack,
serialized on one host). The risk-tiered review work that follows gives every unit a *review* tier: `auto`, `light` or `full`.
Two meanings of "tier" in one pipeline would run through every later change, its specs, its code, its metrics and the words people
use to talk about it. It is cheaper to rename the test kinds once, first, than to carry the collision through ten changes.

The rename also makes the names say what they are. A unit test and an end-to-end test are what people already call them.

## What Changes

- **The test kinds are `unit-test` and `e2e-test`.** Task-group tags `[unit-test]` and `[e2e-test]` become `[unit-test]` and `[e2e-test]`.
  A `TestTier` enum with those values replaces the string constants and the `tier` fields of a planned and a stored unit.
- **Everything abk writes or shows uses the new names:** settings (`e2e_*` become `e2e_*`, `unit_test_*` become `unit_test_*`), the
  `--e2e-test-time-limit` flag, the lock file and output directory, the run logs, the graph node, metrics (`abk.e2e.*` become
  `abk.e2e.*`), spans, and the status context a forge shows (`local/e2e-test` becomes `local/e2e-test`).
- **The internals are renamed too:** modules, classes, functions, test files and fakes, docs and skills, so the code reads the same
  as the words.
- **The old names are read, with a notice, for one release**, by the layer the previous change adds (`test-kind-names-are-accepted-both-ways`, which this change builds on),, at the three edges where they already exist outside the code: the
  headings of a `tasks.md`, the keys of an `abk.yaml`, and the values already in a state file. Nothing is ever written under an old
  name.
- **A guard test** keeps the old names out of the framework outside the one module that reads them.
- **The rename is applied by a committed tool, in slices.** A rename this size cannot be one unit, so a tool performs it on a part of
  the tree at a time and leaves a thin alias behind for each renamed module and symbol until the last slice removes them. The tool stays afterwards for one more use, over a planning repository's documents, and is deleted by the change that ends the build-out.

## Impact

Behaviour is unchanged. Anyone reading metrics by name, scraping the lock file path, or matching a forge status context by name
needs the new names, and the changelog says so. `tasks.md` files and `abk.yaml` files keep working unchanged for one release.
