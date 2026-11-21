# Category: README drift

Weekly-cadence category (run via `improve.md`) — commit history doesn't
need a daily look. Projects commonly document a convention in their
`CLAUDE.md` along the lines of "keeping READMEs current": if a change
adds, removes, or reshapes an exposed endpoint, an outbound call to
another service, or a core logic flow, that service's `README.md` must
be updated in the same change. Changes that are purely internal
(renames, refactors, config tweaks with no effect on API surface or
integration points) are exempt. Read this project's own wording. Where
it documents cross-repo edges (a "dependencies on <repo>" table, a
"known consumers" or "contracts" section), the same rule extends to
those tables — check them too.

Look at this run's project's recent commit history (`git log`) per
service directory. For each service whose route files, client modules,
or core graph/node logic changed without a corresponding `README.md`
change in the same commit range, report it as a finding — service, what
changed, what the README is missing or has wrong now.

Don't flag purely-internal changes (the convention explicitly exempts
them) — use judgment on whether a given diff crosses that line, the same
way you would if you were the one making the original change.
