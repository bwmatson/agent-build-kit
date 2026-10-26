## From `a-restack-takes-no-slot-and-runs-when-seen/2`

- When the usage guard refuses with no reset time (`resume_at()` returns None), `RestackLane.defer_until` records nothing. The unit is then retried in the same tick only if a pause marker it saw is cleared; otherwise it waits for the next tick. That is probably fine, but neither the docstring nor a test says so.
