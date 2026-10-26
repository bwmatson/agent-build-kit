# unit-timeline-is-recorded

Gives every wait in a unit's life a reason and a timestamp: why a unit is not running (blocked,
queue full, no slot, usage pause, lease, backoff, waiting for review, needs a person, ready), when it
became ready and when a person first answered, how many slots sat idle while work waited, and the
report that turns those records into wall time by cause.
