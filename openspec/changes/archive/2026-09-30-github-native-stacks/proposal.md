# Proposal

## Why

The pipeline stacks pull requests already: `base_of` returns a unit's newest
still-open same-repo dependency, the pull request is opened against that branch,
and `restack` rebases the chain when something merges. What it does not do is
tell the host that these pull requests are one series.

That matters now because the host's stacks are an **explicit object**, not an
inference. Pull requests whose bases happen to chain are only a *candidate*: the
host offers to link them and waits to be told. Until it is told, a reviewer sees
what this workspace sees today — six open pull requests, with the ordering
recorded only in prose the pipeline writes into each body.

What registering buys, in the order it matters here:

- **The reviewer sees the series.** Each pull request carries its position and
  the stack's size, and the host renders the order. Review is this pipeline's
  bottleneck; the queue is what a person has to hold in their head.
- **One merge instead of a vigil.** A whole stack, or any contiguous group from
  the bottom, merges as one atomic operation, and the pull requests above are
  rebased and re-targeted automatically. Today merging the bottom means waiting
  for the next tick to restack, then merging the next, and so on.
- **Protection rules are evaluated against the stack base.** Required reviews and
  checks apply as though each pull request targeted the trunk, rather than the
  branch below it — mid-stack enforcement without per-branch rules, and without
  needing rulesets at all.

## What Changes

- **A unit's pull request joins its stack when it is opened.** The first two
  pull requests of a chain create the stack; each later one is appended. This is
  one call per unit, with the pull request numbers the pipeline already knows,
  bottom to top.
- **The forge declares whether it has stacks**, as it already declares whether it
  deletes a head branch on merge. A host without them keeps today's behaviour,
  and nothing in the pipeline assumes the feature exists.
- **Registration never costs a unit.** A host that refuses — the feature absent,
  the repository ineligible, a chain the host will not accept — is reported once
  and the unit proceeds exactly as it does now. A stack is a convenience for the
  reader, not a precondition for the work.
- **The pipeline keeps owning rebases.** There is no API to ask the host for a
  cascading rebase, so `restack` stays as it is. What changes is that the
  pipeline must tolerate the host moving branches *itself* after a stack merge:
  the pull requests above a merged one are force-pushed and re-targeted without
  the pipeline doing it.
- **The pull request body stops asserting what the host now shows**, and instead
  says what the host cannot: whether the chain is linear, since a non-linear
  stack cannot be merged until it is rebased.

Out of scope: merging. The pipeline never merges its own pull requests, and a
stack merge is a person's action in the host's own interface.

## Impact

- **agent-build-kit**: the forge, the step that opens a pull request, the pull
  request body, and the poller's tolerance of a branch the host rebased.
- No change to how units are planned, built, reviewed or rebased.
- One unknown is carried deliberately: the host's documentation does not say
  whether stacks are available for a private repository on a free plan, and one
  repository in this workspace is exactly that. The graceful-degradation
  requirement above is what makes that safe to find out in production.
