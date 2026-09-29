This workspace is a set of repos built by an unattended, spec-driven pipeline
(`abk`). Every change is an OpenSpec change in this planning repo; the
pipeline turns its task groups into branches and pull requests in the repos
below.

Repos:

{repos}

Conventions that hold across every repo:

- Two test tiers. Tier 1 is the ordinary suite, run on every pull request in
  CI with no external services. Tier 2 needs the real local stack and is run
  serially on one host; a task group says which tier it needs.
- Tests mirror the source layout: a test lives in the folder matching its
  module's folder under the package root. Integration tests — anything that
  needs a datastore or the stack — live under `tests/integration/`, mirrored
  the same way. A file that mixes marked and unmarked tests is split.
- No test calls a live website. Recording a fixture from one, and replaying
  that recording in a test, is fine — the test names where the recording
  came from.
- A contract that crosses a repo boundary changes additively first: the
  widening lands alone, every consumer moves, and only then is the old shape
  removed.
- A new module or interface earns its keep by how much it hides, not how
  little it exposes: prefer one call that does the work over several thin
  ones that mirror the caller's own steps, and don't let one module's
  internal shape (a config's nested fields, an enum's exact members) become
  something a distant caller has to know just to use it.
