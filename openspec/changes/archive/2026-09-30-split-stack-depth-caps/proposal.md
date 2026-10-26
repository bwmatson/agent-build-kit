# Proposal

## Why

`stack_depth_cap` is checked in exactly one place: `ready_units`, deciding whether a `planned` unit
may start. It has never gated restacking — `_record_merge` rebases every direct dependent of a
merged unit unconditionally, with no depth check at all. That restacking has stayed safe only
because of an invariant the build cap happens to produce: a unit can only start if its chain of open
ancestors is within the cap, and a chain's depth never increases afterward, only decreases as
ancestors merge. So today, an open unit's depth is always within the build cap, and restacking never
has to reach further than that by construction.

The name has been carrying two responsibilities that were never distinguished, because there was
only one cap to distinguish them with. Separating them is worth doing now for a reason this session
surfaced repeatedly: a cascading rebase costs an agent call to resolve conflicts, and the deeper the
chain, the more of those a single merge can trigger. An installation may reasonably want to allow a
deeper stack to build — more units in flight, more parallel review — while still bounding how far a
single merge is willing to cascade an automatic conflict resolution before it asks a person instead.

## What Changes

- **`limits.stack_depth_cap` is renamed to `limits.stack_depth_build_cap`.** Its meaning and every
  behaviour it gates are unchanged; only the name now says what it has always done.
- **`limits.stack_depth_rebase_cap` is added**, defaulting to whatever `stack_depth_build_cap`
  resolves to when not set explicitly, so an installation that sets only the build cap sees no
  change in behaviour at all.
- **A merge restacks a dependent only within the rebase cap.** When a unit merges, each direct
  dependent's depth is recomputed against the graph with the merge applied, as it is today; a
  dependent whose depth is still within the rebase cap is restacked as before, and one beyond it is
  held for a person instead, with the reason on its record and its branch kept rather than deleted
  out from under it.
- **A held-for-depth unit is reconsidered on a later merge.** Depth only falls as ancestors merge, so
  a unit held this way is checked again whenever another merge in its repo lands, and is restacked
  automatically once its depth is back within the cap — no person has to notice and retry it by
  hand.

## Impact

- **agent-build-kit**: the configuration schema and its validation, and the restack step of
  `_record_merge`.
- **This installation's `abk.yaml`** currently sets `stack_depth_cap`, which will no longer be a
  known key once this lands; it is updated to the new name in the same change to this repo, done by
  hand once the framework change merges — not something the framework's own tasks cover, since this
  repo is not one of the workspace's buildable repos.
- With the default in place, nothing about current behaviour changes until an installation sets the
  two caps to different values.
