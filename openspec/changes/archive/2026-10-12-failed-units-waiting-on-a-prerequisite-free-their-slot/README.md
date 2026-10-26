# failed-units-waiting-on-a-prerequisite-free-their-slot

A failed unit that waits on another unit (an unmet `Needs:` gate, a predecessor not yet reviewed or merged, or one being reworked, failed or
held) no longer counts against `max_units_in_progress` while it waits, and counts again the moment the wait ends. It stays `failed`, is never
requeued by the pipeline, and is shown as `failed, waiting on <units>`. It extends `blocked-units-free-their-slot`, which did the same for
planned units, so the queue no longer fills with failed units whose prerequisites cannot finish, and nobody raises the limit by hand.
