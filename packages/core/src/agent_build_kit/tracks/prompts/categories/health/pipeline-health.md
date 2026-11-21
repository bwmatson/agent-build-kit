# Category: Pipeline health (async pipelines + job state)

Daily-cadence category (run via `health.md`) — a quick pulse check over
roughly the last 24h, not a deep audit, for the one project this run is
about. Check the asynchronous pipelines and job state *this project*
owns — its `CLAUDE.md` and service READMEs describe them. The usual
shapes:

- **Event streams it produces to or consumes from** (a message broker,
  a queue): consumer lag and repeated offset-commit failures per
  consumer group, via the broker's console or CLI. Stay on the topics
  and consumer groups this project's services own; the broker itself
  belongs to whichever repo hosts it.
- **Long-running job state** (a crawl, an ingestion, a batch run): the
  failure rate and retry-budget exhaustion across recent jobs. Respect
  the project's own documented conventions on retries — if its
  `CLAUDE.md` says stale jobs resume only at startup or by hand, don't
  propose a recurring auto-retry timer, even if it looks like it would
  "fix" a stuck-job pattern you find.
- **The platform side**, when this project hosts a pipeline for other
  repos: the broker's own health (disk, partitions, connector errors),
  an ingestion service's pipeline status, documents stuck in a
  processing/failed state.
- If the project's `CLAUDE.md` names none of these, say so in one line.

Report concrete findings: which pipeline/job type, what's failing or
lagging, how often. Don't propose a fix — `health.md` decides what to act
on after seeing every category.
