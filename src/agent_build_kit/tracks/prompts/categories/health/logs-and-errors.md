# Category: Logs and errors

Daily-cadence category (run via `health.md`) — a quick pulse check, not a
deep audit, for the one project this run is about. The project's
`CLAUDE.md` says where its containers' logs are collected (often one
central log store hosted by another repo in the workspace) and whether a
skill exists for querying it — use that skill if there is one, don't
hand-roll queries from scratch. Scope every query to this project's
containers (a label carrying the compose project name, or this project's
service names — the `CLAUDE.md` or the log store's config says which
labels exist). Query the last 24h across this project's services and
report:

- Error/warning rate per service — flag anything trending up, not just
  absolute spikes.
- New exception signatures that weren't present in prior runs (check this
  project's most recent run-log entries, in the run-log directory the
  parent prompt named, for what was already known).
- Recurring exceptions that look like an actual bug (not expected noise —
  e.g. a retry that's supposed to fail a few times before succeeding).

Report concrete findings: service name, the log line/exception, roughly
how often, and whether it looks like a real bug worth fixing vs. expected
behavior. Don't propose a fix yourself — that's `health.md`'s job after
it's seen all categories' findings.
