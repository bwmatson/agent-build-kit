# Tasks

Acceptance: none — this is git configuration on the pipeline's own invocations plus a prompt
change, with no surface a consumer drives; tier-1 tests over a repeated conflict prove it.

## 1. [agent-build-kit] [tier1] Replay a conflict resolution, and confirm it

Done when a conflict resolved in one unit's restack is replayed in another's, the replayed
resolution is left unstaged for the resolver to confirm, and the operator's own checkout keeps
its own behaviour.

- [x] 1.1 Test: a conflict resolved while restacking one branch is replayed when the same
      conflict arises restacking another branch of the same repository, using the cache in the
      common git directory — with nothing copied between worktrees.
- [x] 1.2 Test: a replayed resolution leaves the path unmerged and unstaged; a restack does not
      complete until something stages it; and the resolver is told which paths carry one.
- [x] 1.3 Test: a resolver that overrides a replayed resolution has its own resolution recorded
      in its place.
- [x] 1.4 Test: the setting is passed on the pipeline's git invocations and the repository's
      stored configuration is unchanged; a conflict with no recorded resolution behaves as it
      does today; the port step is untouched.
- [x] 1.5 Enable it centrally for the restack path's git invocations, with automatic staging
      explicitly off.
- [x] 1.6 Tell the resolver in its prompt which paths arrived with a replayed resolution and ask
      for a verdict on each.
- [x] 1.7 Say in `docs/architecture.md` where the restack is described that resolutions are
      reused within a repository, that they are never staged automatically, and that the cache is
      shared with anyone who enables the feature in that checkout.
