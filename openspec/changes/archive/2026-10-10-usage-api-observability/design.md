# Design

## The record

Each use of the endpoint appends a line to a local record: the time, the caller, the outcome, the status code if there was one,
the latency, and the headers of the answer whose names concern rate limits or retrying, kept whatever the outcome. A call
answered from the cache is recorded as such, with the age of the reading, so the hit rate is known. The record is
`usage-calls.jsonl` in the state directory, beside the usage ledger, and is gitignored the same way (the ledger is rolled
up per change when a change is archived; this record belongs to no change, is append-and-close like the run logs, is
kept for a week, and is not rolled up). It holds no token. Every reader of the endpoint writes to it, not only the guard:
the runtime's `get_usage_status` and the tracks runner call the same read, so the recording sits in the one read, below
its callers, and a caller names itself.

## The reading

From the record the pipeline derives, over the last hour and the last day: the calls, by outcome and by caller; the share
answered from the cache; the refusals and the last one's time; for each refusal the quiet time since the call before it and the
number of calls in the preceding fifteen minutes; and the shortest interval between successful calls that no refusal has
followed within a safe margin. The last is the observed safe rate. The status command prints one line, for example how many
calls were made in the hour, how many were refused, and the interval now in use. The same figures are exported as a counter by
outcome and caller and a gauge for the interval in whole seconds (`telemetry.level` takes an integer), so the metrics page shows them with the other pipeline metrics, from the
record when the metrics store is not available.

## The interval

The time a good reading is kept starts at its configured value, fifteen minutes by default, which is also the shortest. After a
refusal it doubles, up to a configured maximum (an hour by default), and the refusal's own retry time, when the answer names one,
is respected over it. After the same time again without a refusal it is halved, never below the configured value. This is a
slow search for the longest interval that works and the shortest that does not refuse, and it uses the record only through the
reading, so it can be explained: the status command says the interval and the refusal or the quiet that set it.

## Not here

The cache, the cool-down after a refusal and the fallback to an older reading are in `usage-pause-deadline`; this changes the
time the cache is kept and adds the record and the reading.
