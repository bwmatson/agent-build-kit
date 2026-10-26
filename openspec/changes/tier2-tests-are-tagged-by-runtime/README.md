# tier2-tests-are-tagged-by-runtime — e2e-test splits

The directory keeps its name because renaming it would orphan the stored units of the change (their ids, branches and run records name it). The change is about **e2e-test splits**: a repo
declares named subsets of its e2e-test tests (`tests.e2e_splits`, see `tier2-splits-replace-runtime-tags`, which migrated the first groups from runtimes to splits), and a split can be held, by
hand, by the configuration or by its gate, so a backend that is down or out of budget parks only that split's tests instead of failing the suite. A unit whose own tests include a held
split passes what ran, waits planned with the split named, and resumes only that split when it is released, with no rework round, no record of a failure on the base and no success
posted for tests that did not run. The open-fix gate and the record of base failures become per split. The kit's own live tests are tagged `runtime_claude_code` and `runtime_acp` (its
choice of markers; an installation declares them as its `claude_code` and `acp` splits), with Claude variants of the build, graph and telemetry tests (the ACP parameters of the build, graph and telemetry tests, the forbidden-command test and the session-listing test are added later by `acp-variants-of-the-runtime-tests`), and the scheduled whole-suite run
becomes one change per split. A hold is `hold: true` on a split in `abk.yaml` together with `e2e-held.json` in the state directory, the configuration winning, set with
`abk e2e-test hold|release|status`.
