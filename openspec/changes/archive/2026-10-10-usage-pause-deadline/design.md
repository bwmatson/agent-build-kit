# Design

## The deadline

Every deadline the guard produces is the later of the time it computed and now plus the unknown-retry interval
(thirty minutes today, not a short one), and the grace period is added in one place. The two intervals and the
grace move into `pause.py`, which `usage_guard.py` repeats as a second copy of each today, so that there is one definition
of each and one place the grace is added: `pause_until` adds it to a time it is given, and the guard's own
computation (`_resume_after`, `_resume_to`) no longer adds it too. A reading's reset time that is not in the future
is treated as unknown, which means "ask again after the unknown-retry interval". The same rule covers the branches
for a reached spend limit and for credits, which share the computation.

## A stale reading

A cached reading older than the allowed age still refuses a start, as now. The pause it causes no longer reads
the reading's window: it lasts a new stale-retry interval, five minutes by default and configurable with the cache time below
(the unknown-retry interval is too long to wait on a reading that is only old), and its reason says the reading is
stale and where it came from. Because a usage pause is asked again every round, the first round with a trustworthy reading
clears it.

## What a reading says it is

A reading served from the cache file is labelled `live` today, so it passes for a fresh one and skips the staleness
test, which exempts live readings. A reading that comes from the cache, whether within the cache time or kept past it
as the last good one, gets its own source (for example `cache`), so the staleness test and the reason a start was
refused both see what it is. Only an answer the endpoint has just given is `live`.

## Reading usage

The usage endpoint rate-limits, and what it allows is not published: it answered 429 on one call and 200 on the next some minutes
later, and a successful answer carries no rate-limit headers, so the number of requests a window allows is not known. The
guard cannot find it out, so it asks less. A good answer is cached for fifteen minutes by default (configurable, on
`ClaudeLimitsConfig`, which holds the settings of both windows and so is where a setting about the account's endpoint
belongs, not on `UsageWindowConfig`, which is per window), up from three, and every reader in every process uses the
cache. The readers are the usage guard's start check, the pass's check, the runtime's `get_usage_status` (which calls
the live read directly, with its own fallback) and `Node.gate`, which today asks `may_start` and then `resume_at`, and
each of those reads usage on its own, so a gate reads twice. All of them go through the same cache, and the gate asks
once.
A unit's run is longer than that, and the thresholds are applied to a reading that is at most fifteen minutes old; the nearer a
window is to its reset, where the ramp makes the threshold move, the more a stale reading matters, so the cache is bounded by
the time left in the window and a reading is never kept past its window's reset.

The usage endpoint rate-limits: called directly it answers 429 Too Many Requests, and every gate, status call and editor
session asks it. A failure is not cached today, so each gate asks again at once, which keeps it limited. After a 429 the
guard makes no call until the time in the answer's retry header, or a short default when it has none, and uses the last good
reading meanwhile; a timeout or a connection error is retried once after a short delay. A cool-down is kept with the cached
reading so every process honours it.

The order is: the live call, outside any cool-down; the last good live reading kept in
the cache, while it is younger than a longer fallback age (30 minutes by default, configurable); the editor's
cached reading. The reason a start was refused names the source it rested on, and a failed live call records
its cause (a status code or an exception name), logged once per tick at warning level. Failures are still not
cached as readings.

## The pass

A refused start for usage pauses only the unit that asked. A `rate_limit` pause, written when the model itself
refuses a build, is different: it still stops new builds for the pass until its deadline, because the refusal is
the model's and says nothing about the usage endpoint. The pass loop does not enter its stopping state because of a
usage pause; it keeps running its rounds, so merges, comments and state are recorded as usual, asks the guard
again at each round, admits builds again as soon as it allows, and resumes units paused for usage within the
same pass. Units paused for usage keep their places in progress as they do now. A pause that comes from real
exhaustion still refuses every start, because the guard says so every round.

## Output

The line that says a pause is until a time prints the time in local time with its reason, and is never earlier
than the moment it is printed.

## The usage module is the only authority

Every run asks and the module decides. The tick, the pass's rounds, the gate before an agent step, the tracks and the status
command all ask the usage module for a decision, every time; none of them keeps a view of its own. The module answers from
the cache file and calls the endpoint only when the cached reading is older than the cache time, past its window's reset or
absent, and then at most once in that time however many askers there are.

One process refreshes at the expiry. Reading the cache file, calling the endpoint and writing the file happen under a file
lock (the cool-down is read under it too, so a second process cannot start a call a first has just been rate-limited on). A
process that finds the lock held does not wait to call: it serves the last good reading, labelled as from the cache, and the
wait is counted. The existing `file_lock` blocks until free, which is right for the unit store but not here, so this needs a
non-blocking take. The cache file is written whole (to a temporary file and renamed), since a reader outside the lock must
never see half of one.

The marker is a record, not an authority. The pause marker is shown by the status command and read to know whether to log
"pausing" or "resuming", and a `rate_limit` pause, which comes from the model's own refusal, is honoured to its deadline. A
usage marker refuses nothing: `run_round` already asks the guard and clears the marker when it allows, and the gate asks the
guard through the runner. The tracks runner never reads the marker. Two readers in the pass loop still treat any marker as a
reason to stop: the pass's stop flag (which group 3 narrows) and the tick's "paused" outcome after a round that started
nothing. Both must read a `rate_limit` marker only, so a usage marker left over from a stale reading can never show as, or
cause, a stop after the guard has said yes.

A reading is never used past the reset of its window, whichever source it came from: the cache file's reading is already
dropped there, the last good one kept as a fallback likewise, and the editor's reading, which the guard takes when the live
one fails, is held to the same test.

A step that began under the threshold finishes. The threshold is applied when a start is asked for, not while a step runs, so
exhaustion in the middle of a run is noticed at the next gate (the next start, or the next agent step's gate), which refuses
it. Nothing kills a running step.

A `rate_limit` pause stops new builds only until its deadline, and the stop is worked out again each round from the marker,
not kept in a flag that a first refusal sets for the rest of the pass. When the deadline passes within a pass, the next round
submits the ready units. A build that returns failed for another reason still ends the pass's admissions as before.

The cache reports hits, misses, expiries (a reading found past its time or its reset) and waits on the lock through the
existing telemetry, so the fifteen-minute default can be tuned from what the pipeline does. The record of each call stays in
`usage-api-observability`.

Outage resilience is the business of `usage-read-on-decision`, which allows a start from a reading older than the fallback age
when it is far under the threshold and its window has not reset, so a long outage of the endpoint does not stop work that no
reading could have refused. It is not repeated here, and this change keeps the stale rule above for a reading that cannot be
shown to settle the decision.
