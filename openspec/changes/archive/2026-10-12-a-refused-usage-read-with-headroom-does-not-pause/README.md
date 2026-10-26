# a-refused-usage-read-with-headroom-does-not-pause

When the usage endpoint refuses a read (or the minimum interval holds a call back) and the guard's own cache holds a last good reading of any
age, the guard estimates each window as that reading plus a flat allowance per unit that has spent or been admitted since, and allows a
start while the estimate plus a margin stays under the threshold, up to a cap of starts per reading. A refused read no longer pauses the
pipeline when the last good reading showed ample room. It also stops a refusal that asks for no wait from widening the time a reading is
kept, and lowers the default ceiling of that time to thirty minutes. It extends `usage-read-on-decision`, `usage-pause-deadline` and
`usage-api-observability`.
