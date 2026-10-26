# Proposal

## Why

A restack that conflicts hands the conflict to a model. That is the right fallback, and it is
paid for every time — including when the conflict is one the pipeline has already resolved in
another unit of the same stack, which is common: units in a chain touch the same files, and a
predecessor's merge produces the same hunk against each of them.

Git solves exactly this with `rerere`: it records how a conflict was resolved and replays that
resolution when the same conflict reappears. Two facts make it fit here without any plumbing:

- **The cache is already shared.** From inside a unit worktree,
  `git rev-parse --git-path rr-cache` resolves to the repository's common git directory — the
  same path the main checkout reports. A resolution recorded while restacking one unit is
  therefore visible when restacking the next, with nothing copied.
- **It is not enabled anywhere.** No `rerere` setting exists in this framework, so every
  recurrence is resolved from nothing. Today that cost two agent resolutions of one hunk.

## What Changes

- **The pipeline enables `rerere` for its own git work** in the restack path, so a recurring
  conflict arrives with its recorded resolution already applied to the file.
- **`rerere.autoUpdate` stays off, deliberately.** The replayed resolution is written into the
  working tree but left unstaged and still marked unmerged, so nothing is carried forward
  unexamined: the resolver's job becomes checking a proposed merge and staging it, rather than
  deriving one.
- **The resolver is told when a hunk carries a replayed resolution**, so it confirms rather than
  starts over — and can reject it, which is the point of leaving it unstaged.
- **The repository's stored configuration is not changed.** The setting is passed on the
  pipeline's own invocations, so an operator working in the same checkout is unaffected unless
  they enable it themselves.

## Impact

- **agent-build-kit**: the git invocations in the restack path, and the resolver's prompt.
- Cheaper restacks where a conflict recurs — a confirmation instead of a derivation — and no
  change at all where it does not.
- Nothing about the adapt step changes: a port is not a conflict resolution, and `rerere` has
  no bearing on it.
