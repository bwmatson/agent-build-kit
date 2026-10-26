# Tasks

Acceptance: none — this is the pipeline's own build loop, with no surface a
consumer drives; what proves it is tier-1 tests through the runner, with real
git for the moves.

## 1. [agent-build-kit] [tier1] Check the base against the remote before a run and before a push

Done when a run starting from existing commits fetches before it restacks, a
unit about to push fetches, learns of a merged parent from the forge and moves
onto its base first, a clean move pushes with no agent call and its approval
kept, a conflicting move or a tier 1 failure holds the unit instead of pushing,
and a pull request refused for a missing base holds the unit instead of failing
it.

- [x] 1.1 Test: a run that starts with commits on the branch fetches the repo
      before moving the branch, and a fetch that fails is logged without
      failing the unit.
- [x] 1.2 Test: before a push, a branch behind an advanced trunk that replays
      cleanly is moved, tier 1 runs again, the push happens, no agent is called
      and no review round is recorded.
- [x] 1.3 Test: before a push, a move that needs resolution pushes nothing and
      leaves the unit planned to resume at its restack with a note saying its
      base moved before its push.
- [x] 1.4 Test: before a push, a parent whose pull request the forge reports
      merged, and the store does not, is recorded as merged through the merge
      handler, and the unit is moved onto and pushed against its new base.
- [x] 1.5 Test: tier 1 failing after a clean move pushes nothing and leaves the
      unit planned for rework with tier 1's output as feedback.
- [x] 1.6 Test: an approved branch moved cleanly passes the push gate without
      another review, and one whose move needed resolution does not.
- [x] 1.7 Test: opening a pull request refused for a missing base leaves the
      unit planned to resume at its restack; any other refusal fails it as now.
      For each forge, its own missing-base error is recognised.
- [x] 1.8 Add a one-repo fetch taken in the repo's turn, and call it at the
      start of a run with existing commits.
- [x] 1.9 Add the check before the push: fetch, fresh base with the parent's
      pull request read from the forge, move, tier 1, then push or hold.
- [x] 1.10 Have each forge report a missing base as its own error, and turn it
      into the hold.
- [x] 1.11 Update `docs/architecture.md` where building and restacking are
      described, and `docs/code-forges.md` for the new error.
