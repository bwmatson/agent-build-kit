# a-failed-unit-resumes-when-its-wait-ends

A failed unit that waits on another unit stays `failed` while it waits (shown as `failed, waiting on <units>`, not counted), and when its
wait ends the pipeline requeues it once, without a person, as it resumes a blocked unit. A prerequisite of a failed unit can only have been
added after it failed, to unblock it, so once it is met the unit should run again. A unit held by a person, a wait that ended because the
prerequisite was closed, and a unit with no wait at all are left for a person, as today. The mode (resume or rework) is picked from what the
store already records, and `global_limits.wait_end_requeue` overrides or turns it off. It follows `failed-units-waiting-on-a-prerequisite-free-their-slot`,
which says such a unit is never requeued; this change supersedes that sentence.
