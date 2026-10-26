# Design

## The invariant that makes the default safe

`depth_of` counts a unit's chain of same-repo ancestors that are still `in_review`, plus itself.
`ready_units` refuses to start a `planned` unit whose depth exceeds the build cap. Dependencies are
fixed at planning time and never added afterward, and a unit's depth can only fall — an ancestor
merging removes it from the `in_review` count, never adds one. So for as long as a unit is open, its
depth is bounded above by whatever the build cap was when it started, and that bound never rises.

That is why defaulting the rebase cap to the build cap changes nothing: a direct dependent's depth at
the moment its ancestor merges is always within the build cap already, so a rebase cap equal to it
is never the reason a restack is skipped. The two caps only diverge in effect once an installation
sets them to different values.

## Where the rebase cap binds

`_record_merge` already re-reads the graph after recording the merge, before it looks at children —
so `depth_of(child, graph)` at that point already reflects the merge: the just-merged unit is no
longer `in_review` and drops out of the count automatically. No new depth computation is needed,
only a comparison against the rebase cap at the point restacking is attempted, for each direct
dependent in turn.

A dependent within the cap is restacked exactly as today. One beyond it is left alone, in the same
sense the code already leaves a unit alone when its restack raises: not attempted, its branch not
touched, the reason recorded. The difference is that this is not a git failure — it is a policy
choice an installation made on purpose by spreading the two caps apart — so it is held rather than
merely logged: `held` is the state that already means "the pipeline will not touch this; a person
does," and a policy-bounded restack is exactly that case.

## The branch must not be deleted out from under it

`_record_merge` deletes the merged unit's old branch once nothing is still building on it, checked
against a list of dependents whose restack was skipped because their build held the branch's lock.
A dependent skipped for depth reasons is exactly as unrestacked as one skipped for that reason, and
must join the same list — otherwise its branch is deleted at the end of this same pass, and the held
unit is left pointing at a ref that no longer exists. This is precisely the failure this session saw
happen by accident once already; here it must not happen by design.

## Self-healing, not a standing hold

A depth-based hold is different from the other two: a reviewer's hold and a toolchain hold both need
a person to change something before retrying helps. This one resolves itself by ordinary pipeline
activity — depth only ever falls, so a merge anywhere below a held unit in its repo can bring it back
within the cap without anyone touching it.

So a merge event, after restacking what it can, also reconsiders every unit in its repo currently
held for this reason: recomputes its depth against the now-current graph, and restacks it if it is
within the cap, exactly as a fresh dependent would be. A unit left beyond the cap after that stays
held, to be reconsidered at the next merge in its repo.

This is a bounded check — only units already marked held for this specific reason, in the same
repo — not a general re-scan of the graph.

## What is not required

No cross-validation between the two caps. A rebase cap larger than the build cap is simply inert,
never binding, because depth never exceeds the build cap while a unit is open — unlike the floor and
ceiling on unit size, where an inverted ordering makes every configuration impossible, there is no
configuration of these two caps that cannot be loaded and run.
