# comments-seen-when-worked

A review comment is recorded as seen only once a unit has taken it. A comment
that arrives while its unit is held used to be dropped on the floor: the handler
declined to requeue a held unit, but the poller recorded the comment as handled
anyway, so it was never delivered when the unit was released.
