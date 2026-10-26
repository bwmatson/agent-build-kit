# the-whole-moved-base-flow-runs-in-the-restack-lane

A unit whose only reason to run is that its base moved no longer waits for a build worker after its move. The restack lane already moves
the branch and settles a conflict with the resolver without a build slot; this change runs everything that follows in the lane too: the
port of a conflict the resolver could not settle, a rework of the conflict kind, tier 1 on the result, the review of the resolved move, the
check against the base and the push. The run takes a lane worker and the lane's own cap
(`project_limits.max_concurrent_restacks`), is never refused for want of a free build worker but counts toward slot occupancy (no build starts at or above the cap), asks the usage guard before every agent call exactly as any run does,
and is one attempt at the base's tip, bounded by `max_review_rounds` and ending in a hold with a reason rather than a loop. Anything that
is ordinary rework (a reviewer's comment, a failing check, tier 2 feedback) is never continued in the lane: the unit is handed back to
the build queue with a cause of its own at the step it reached. `abk status` shows the unit as restacking for the whole run.
