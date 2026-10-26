# a-unit-parked-on-a-split-can-be-requeued

`abk requeue planning-in-the-working-copy/16` was refused on 2026-10-21 ("is planned; only a failed or held unit can be requeued"). The unit is a
started unit parked at its e2e-test step on the held split `acp` (planned, cause `split_held`, `parked_splits` `["acp"]`, a branch, no pull request,
no run). Its test file was tagged for `acp` by mistake, the fix is a code edit by the unit's builder, so the agent has to run again as a rework with
a person's note. The release of the split resumes the unit onto the same tests, and the rule that follows a group's `Split:` fires only when the
group's `Split:` changes. Here `abk requeue` accepts a parked unit when a mode that runs the agent is given (`--rework`, with or without a note, or
`--restart`): it is delivered like any requeue of a unit with a thread, its park, cause and wait record are cleared, and it runs from `prepare`. A
plain requeue of a unit whose parked split is still held is refused, saying what it is parked on and what to give instead. Running, in-review, merged
and in-flight units, and units with a pull request, are still refused. Emergency lane (priority 0).
