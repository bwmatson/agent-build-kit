# a-restack-takes-no-slot-and-runs-when-seen

Moving a unit onto a changed base no longer waits for a build slot or for the next tick. A restack runs in its own small lane, beside the
build workers and outside both `max_concurrent_stacks` and the start gate of `max_units_in_progress`, and it starts the moment the
pipeline sees that a base moved: when the poller reports a merge, when a run holds a unit for a moved base, or when a scan finds a unit
whose branch no longer holds its base. A new `limits.max_concurrent_restacks` (default 2) bounds the lane so a burst of merges cannot start
dozens of resolver runs. The lane honours the usage limits exactly as an agent run does: a clean move spends nothing and proceeds in a
usage pause; the resolver step is admitted by the same guard and thresholds as a unit start, and a conflicting restack waits for the pause.
`abk status` shows what the lane is doing as `restacks: N running, M waiting`.
