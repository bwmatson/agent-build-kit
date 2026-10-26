## From `conflicts-trigger-rework/1`

- If a unit's rework still conflicts, the unit stays in_review and is not reworked again. The poller only sends a conflict back on a transition and does not track head sha. This is best handled together with fresh-base-before-push (earlier optional point 1.2).
- The Azure forge reads no mergeStatus, so a conflict there is never sent back for rework. This is safe because nothing gets marked wrongly. Mapping mergeStatus, or adding a comment in _view that says it is deliberately left unmapped, would make that explicit (earlier optional point 1.3).
