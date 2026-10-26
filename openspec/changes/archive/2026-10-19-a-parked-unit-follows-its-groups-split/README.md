# a-parked-unit-follows-its-groups-split

A started unit parked at its e2e-test step on a held split stays parked when a person edits its group to say `Split: <other>` and its task
text, and the plan is made again: the release step looks only at whether the split the unit is parked on is held, a requeue refuses a planned
unit, and a plain resume would run the e2e step on the old tests. Here, when the `Split:` of the groups a parked unit carries differs from the
split the unit was planned in, and is none of the splits it is parked on, the park ends, the unit is requeued for rework with an automatic note
that says the split and the task text changed, `parked_splits`, `parked_sha` and `parked_snapshot` are cleared and the stored split is brought
up to date, so it happens once. A unit whose split did not change, one still in the split it is parked on, one in flight, and one whose new
split is itself held are left alone. Emergency lane (priority 0): four live units are stuck on it.
