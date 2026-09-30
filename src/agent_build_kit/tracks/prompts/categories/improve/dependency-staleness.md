# Category: Dependency staleness

Weekly-cadence category (run via `improve.md`) — dependencies don't go
stale hour to hour, so a daily check would just be wasted budget. If a
`dependency-update-check` skill is available, invoke it against this
run's project rather than reimplementing it: it scans Docker/npm/uv/
pre-commit dependencies repo-wide, respects a root
`.dependency-update-check-ignore` if the project has one, and only
proposes updates that have been public 14+ days. It never auto-commits —
treat its scan output as this category's findings, and any updates it
recommends applying as candidates for the propose phase (a change whose
tasks write the test and then make the update), not something to apply
directly here. Without the skill, do
the same by hand: list each lockfile's pinned versions against what's
published, and apply the same 14-day rule.

Cross-repo caveat: a dependency pinned or shared across repos in this
workspace (e.g. a package one repo publishes and another consumes
through a path or git source, or a constraint one project's lockfile
inherits from a package it no longer shares a lock with) — flag it, but
mark an update that would need the other repo to move too as a
recommendation, not a candidate.

Report what it found: which dependencies, current vs. available version,
and anything it flagged as a breaking change worth extra care.
