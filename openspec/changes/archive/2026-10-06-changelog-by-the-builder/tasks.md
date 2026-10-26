# Tasks

Acceptance: none — prompts, a test and a review instruction inside the pipeline; tier-1
tests over the prompt text and the changelog check prove it.

## 1. [agent-build-kit] [tier1] The builder writes the changelog entry right, and tier 1 checks it

Done when the build, rework and resolver prompts carry the convention, tier 1 fails on a
badly shaped changelog, and a reviewer is told not to raise its form.

- [x] 1.1 Test: a changelog with a conflict marker, with two bullets run together, with
      a duplicated bullet, with a bullet outside any section, or with headings out of
      order fails the check naming the line; a well-formed one passes; today's file
      passes.
- [x] 1.2 Test: the build prompt, the rework prompt and the restack resolver's prompt
      each contain the convention text taken from the conventions file, and the
      resolver's also contains the keep-both-and-fold rule for the changelog.
- [x] 1.3 Test: the review prompt lists changelog form and wording as not to be raised
      while the check passes, and still names a claim the code does not support as in
      scope.
- [x] 1.4 Write the convention section in `AGENTS.md`, read it into the three prompts,
      add `tests/test_changelog.py`, extend the no-installation-names test to cover the
      changelog if it does not, and add the line to the review prompt.
- [x] 1.5 Fix whatever the check flags in the current changelog so it starts green.
- [x] 1.6 Document the convention and the check in `docs/architecture.md` where the
      checks before review are described, and add a changelog entry.
