# Category: LLM observability (traces)

Daily-cadence category (run via `health.md`) — a quick pulse check, not a
deep audit, for the one project this run is about. The project's
`CLAUDE.md` says where its LLM traces go: typically one OTLP-compatible
tracing backend, possibly hosted by another repo in the workspace,
carrying an LLM gateway's own spans plus each calling service's. Look
only at this project's call sites — the service names it exports traces
under (e.g. `OTEL_SERVICE_NAME` in its compose file) — and say so in one
line if it has none. Query the backend (through its UI's datasource, or
its API directly) for the last 24h and report. **Pass explicit
`start`/`end` bounds on every query** — a trace backend queried without
a time range typically returns only a short recent window (minutes, not
the retention period), which reads as "no traces at all" and produces a
false-negative "tracing gap" finding even when export is working
correctly. Earlier runs have mistaken exactly that measurement artifact
for a real gap, more than once, before anyone checked the query bounds.

- Latency outliers or a trending-up p95 per LLM call site.
- Token usage / cost trend per call site — flag anything that looks like
  it's calling the LLM more often than the logic requires (e.g. a retry
  loop with no backoff, redundant calls in the same request path).
- Error rate on LLM spans — timeouts, malformed-response retries, etc.

Report concrete findings: call site (file/function), the metric, and
why it's worth a human's attention. Don't propose a fix — `health.md`
decides what to act on after seeing every category.
