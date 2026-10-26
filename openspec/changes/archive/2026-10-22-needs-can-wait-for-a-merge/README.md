# needs-can-wait-for-a-merge

A `Needs: <change> group <n> — why` line makes the dependent start on the parent's branch once the parent is in review. That is right for ordinary
stacked work and wrong for a fix to the code that runs the pipeline: on 2026-10-21 three dependents of such fixes (the fixes for
`a-test-only-group-commits-no-pair` and `a-group-already-built-is-satisfied-in-a-stubbed-build`) were started or requeued when the fix entered review,
or by the very tick process that merged it, and so ran the old code. A tick is one long-lived process whose modules load at its start (the
systemd tick ran from 14:46 past 16:15), so the kit checkout being fast-forwarded after a merge reaches only the next tick.

This change gives `Needs:` two kinds. The plain line is unchanged. A line with `merged` after the group number (`Needs: <change> group <n> merged —
why`), deprecated until now, becomes the **merge** kind: the dependent is not started, and a failed dependent is not requeued, until the parent unit has
merged and, when the parent is code the running tick executes, until the tick doing the starting loaded the merge (the tick records the sha of the
kit checkout it started from, and the parent's merge commit must be in it). A merge during a tick therefore defers the dependent to the next tick.
`abk status` says which of the two it waits for, the graph draws the edge differently, `abk tags` stops warning, and the authoring skill says when to
use it. The 21 live `merged` lines already in the planning repo all name parents that have merged, so none delays a unit.

Each dependency edge has a kind, `review` or `merge`. It is `merge` for a cross-repo edge (a plain `Needs:` to another repository is read as `merge`), for an
author's `merged`, and for a failed unit's wait (merge plus the next tick, whatever the kind); otherwise `review`. The planner is untouched and respects an
author's `merged`; a planner-chosen kind is future work. The authoring skill says when to write `merged`.
