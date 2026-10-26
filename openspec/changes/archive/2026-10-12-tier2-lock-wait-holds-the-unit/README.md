# tier2-lock-wait-holds-the-unit

A unit queued behind another unit's tier 2 run no longer fails after an hour of waiting. It keeps waiting, with no deadline, and says so: the wait is
logged, recorded as a span, and names the unit that holds the lock and since when. `abk status` shows the holder and its age, and a holder record left
by a process that is gone is reported as stale and ignored.
