# Proposal

## Why

Of the failures this pipeline hit in one day, most were missing behaviour rather than untested
code — the pipeline failing where it could have asked, retried or waited. Two were not:

- **A gate that could not run where the pipeline runs it.** `pyrefly` in a worktree under
  pre-commit found no files at all and exited non-zero, so a unit's tests commit was rejected with
  nothing wrong in the code. The framework has a single integration test, covering `abk init`, and
  nothing that exercises a worktree, a real pre-commit run, or a workspace member's own checks.
  The environment every build depends on is untested.
- **A parser that looked right and was not.** The set of tests a unit had added was derived by
  matching `def test_…` in the *text* of a diff, which sweeps up any test sitting near an edited
  line, because a diff carries context. That cost a unit, and a fixture of one realistic diff would
  have caught it.

Both are narrow, cheap and specific. Neither is an argument for testing the agent-driven paths,
which are slow, expensive and non-deterministic, and which were not where the problems were.

## What Changes

- **One integration test of the habitat.** A trivial unit is built in a real git worktree and put
  through the repository's real gate, so that a tooling change which breaks the pipeline's
  environment fails a test rather than a unit. Marked so it runs where integration tests run, not
  in the default suite.
- **The text parsers get tests with realistic input** — a diff with context lines, an agent
  transcript that mentions rate limits without being refused, a refusal, a decision block that is
  short of one entry.
- **Tests reach public surfaces only.** Where the behaviour worth testing sits in a private helper,
  either the helper becomes part of its module's interface — named, documented, with its contract
  stated — or it is tested through the public function that uses it. No test imports a private name
  to get at its logic.
- **The convention is written down**, beside the repo's other testing conventions, because it is
  the sort of rule that decays silently.

## Impact

- **agent-build-kit**: a new integration test, tests for existing parsers, and promotion of the one
  derivation that deserves a name.
- A tooling or environment regression that would otherwise surface as a failed unit surfaces as a
  failed check.
- No new machinery, no change to any behaviour.
