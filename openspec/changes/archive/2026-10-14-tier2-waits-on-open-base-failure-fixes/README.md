# tier2-waits-on-open-base-failure-fixes

While a failure that also fails on the base has an open fix change, no other unit of that repo starts a full-scope tier 2 run (a run that executes the
whole marker; an own-scope run, which executes only the tests the unit added or changed, is never held). A tier 2 run is tens of
minutes of real agent calls and every unit would meet the same failing test. The fix change the pipeline already writes is the blocker: the
unit about to run tier 2 is given a `Needs:` line on it, through the same function the unit that met the failure uses, and parks as that
unit does. The fix change's own units, units already waiting on it and units of other repos run as before. No new cause, command, record or
setting.
