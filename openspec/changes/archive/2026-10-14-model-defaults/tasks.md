# Tasks

Acceptance: none — defaults and documents; tier-1 tests prove the resolution.

Priority: 4

## 1. [agent-build-kit] [tier1] Sonnet builds and reworks, opus reviews

Done when the Claude Code runtime's defaults are the new ones and every document that states them agrees.

- [x] 1.1 Test: with no models block the Claude Code runtime resolves `sonnet`, `sonnet`, `opus` and `opus` for
      implement, rework, review and rework_review; a flat block naming only one role keeps that role and defaults the rest;
      an environment override wins; a runtime with no declared names resolves every role to empty.
- [x] 1.2 Test: no test or document still asserts or states the old defaults; update the tests that pin `opus` for
      implement and rework and `fable` for the rework review: `tests/pipeline/test_wiring.py` (about lines 716-757, the
      build, standard review and rework review model checks) and `tests/test_runtime_selection.py` (lines 77, 100, 108
      and 154, and the flat block at line 26). The stub runtimes that inherit `ModelsConfig()` as their declared names
      (`tests/runtimes/stand_in.py`, `tests/runtimes/selectable.py`, `tests/runtimes/test_runtime_registry.py`) take the
      new defaults too, so check what they assert.
- [x] 1.3 Change the default model block (`ModelsConfig` in `config.py`) and its docstring and the comment on `rework_review`,
      which still say the rework's reviewer is a third model.
- [x] 1.4 Update `docs/configuration.md` (the models block and its comments), `docs/architecture.md` (the line near 1030 that
      says a rework is reviewed by a different model, which now holds because the author is `sonnet` and the judge `opus`), `docs/agent-runtimes.md` (the example,
      the sentence naming the declared names, and the alias table row) and the configuration skill's example, saying that
      both reviews are made by a different model from the author, and add a changelog entry saying that the defaults changed
      and that naming models keeps the earlier ones.
