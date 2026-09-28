# Category: Resource usage (container and host metrics)

Daily-cadence category (run via `health.md`) — a quick pulse check, not a
deep audit, for the one project this run is about. The project's
`CLAUDE.md` says where its metrics live: typically one metrics store
(possibly hosted by another repo in the workspace) scraping per-container
CPU/mem/network/disk and host-level metrics on a short interval; the
hosting repo's compose file or docs usually document how container
names join onto the metric labels — read that rather than guessing the
join. Restrict container metrics to this project's containers (its
names: `docker ps --filter label=com.docker.compose.project=<project>`).
Query the last 24h and report:

- Container restart counts — any service restarting more than
  occasionally is worth flagging even without a known cause yet.
- CPU/memory trending up over time for a service with no corresponding
  load increase (a leak, not just "it's busier now").
- OOM kills.
- Host-level headroom: disk space, load average — when every repo in
  the workspace runs on one host, host exhaustion affects every service
  at once. Report host-level problems in whichever project's run
  notices them; `tracked-issues.md` dedup keeps them from becoming two
  PRs.

Report concrete findings: service/host, the metric, the trend, and
roughly how urgent it looks. Don't propose a fix — `health.md` decides
what to act on after seeing every category.
