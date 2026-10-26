# Design

## Context

"Unit-test" and "e2e-test" appear in about 48 source files (some 580 lines), 272 test files (some 2000 lines), 11 documents, the web UI,
the skills, the metric catalogue, state-file names, and four modules named `e2e-test*`. The pipeline's ceiling on a unit is 750 changed
lines, and a unit larger than that is refused (`GroupTooLarge`), so the rename cannot be one group.

## Decisions

- **Names.** The enum `TestTier` has the members `UNIT_TEST = "unit-test"` and `E2E_TEST = "e2e-test"`: the stored and tagged
  value is the same string, and the `-test` suffix keeps the tag apart from "unit" meaning a pull request's worth of groups.
  Settings use underscores (`e2e_*`, `unit_test_*`); node, class and module names use `e2e` (`Node.E2E`, `E2eResult`, `e2e.py`).
  The status context a forge shows is `local/e2e-test`; hyphenated names already work on both forges (labels such as `agent-hold`
  are in use), and Azure DevOps splits a context into a genre and a name at the slash.
- **One compatibility module, from the change before this one.** `test-kind-names-are-accepted-both-ways` creates it and the reading of both spellings at the three edges, and this change builds on it. The old spellings are known in one module (`compat_names.py`): a table of old-to-new for tags,
  settings keys, stored values, state-file names and metric names, with the notice text. Every other module imports the new names.
  Reading goes through it; writing never does.
- **The rename is a tool, applied in slices.** `agent_build_kit/rename_test_kinds.py`, run as a module, rewrites identifiers, strings, comments, file names and
  documents under paths it is given, from the table in the compatibility module. It is idempotent (a second run changes nothing) and
  has a `--shims` mode: for each module or symbol it renames in a slice, it leaves the old module or name importable as a one-line
  alias, so code in a slice not yet converted still imports. Each slice is one group, reviewed as the tool's change plus its result.
  The last slice runs the tool with `--remove-shims`, turns the guard test strict, and keeps the tool and its tests: a person runs it once more, over the planning repository's Markdown, after the rename lands (an installation's runbook says when), and the change that ends the build-out deletes it. Test fakes at the top of `tests/` are renamed
  with the same shims, since tests in every slice import them.
- **Slices follow the code.** The source in `pipeline/`, then the rest of the source and the web and skill templates; the tests in
  the order of the table of groups (by directory, and `tests/pipeline` in six parts by file name, since it holds half the test
  references); the documents last. Each slice leaves the suite passing, which the shims make possible.
- **The rename of open changes.** An open change's `tasks.md` keeps its old tags and still validates, with a notice. A later change
  rewrites them in bulk; this one only has to keep them working.
- **Stored state.** `units.json` and `planned.json` are read with either spelling and rewritten with the new one the next time they
  are written. The lock file and the output directory are renamed on first use: if the old name exists and the new one does not, it
  is moved; a lock held under the old name is honoured until it is released.
- **Metrics.** The instruments are renamed outright. A dashboard that reads `abk.e2e.*` must change; the changelog says so. The
  catalogue helper (`tests/metric_names.py`) is updated with them.

## Risks

- **Conflicts with in-flight branches.** The slices touch most of the tree. They are planned to run when few units are in flight, and
  restack and adapt carry the rest.
- **A slice that is bigger than estimated.** Sizes are counted from matching lines; the planner's calibration applies, and a slice
  that proves too large is split by directory, not by weakening the tool.
- **A missed spelling.** The guard test greps for every spelling the table lists, case-insensitively, so one is found by the suite.
