# a-unit-start-forecasts-its-usage-by-tier

The second half of the usage-estimation work (the first is `usage-is-estimated-from-recorded-cost`, which estimates what was spent
since a reading from recorded cost and learns `points_per_usd`). This change estimates what a unit **will** spend, so a start is
judged by what the unit is expected to cost and not by a flat allowance. The forecast is, over the steps a unit of its review tier
runs and the rounds of each, the chance the unit reaches the round times the mean cost recorded for that step at that round,
converted to points. It uses each tier's own recorded history once there is enough of it, and the flat per-unit allowance until then. Units
already running add the remaining expected cost of their current step, and plan calls and tracks due before a window resets reserve
theirs. A refusal names the role that dominates the forecast. `abk status` shows the forecast beside the estimate and `abk report
--by tier` compares forecast with actual. The emergency lane and the cap on starts per reading are unchanged.
