# Propose — agent-build-kit — 20261028-133512

## Tracker refresh
`grafana-url-env-test` (change `agent-build-kit-track-20261026-125001`): the change directory is still under
`openspec/changes/` (holding only a lock file), not archived — left as in flight.

## Candidates read
The two health runs (20261027, 20261028) list none. The 20261028-133512 recommend run lists three:

1. `StoredUnit.merged_at` refactor — skipped: needs a decision on tie-break and unparsable-stamp behaviour.
2. `readEvents` test in `web/src/agui.ts` — **chosen**: concrete, test-only, one file, trivially revertible.
3. `elicitation/create` decline in `runtimes/acp.py` — skipped: the gap is unverified and the work depends on a check.

Each was its own issue; no two competed.

## Change written
`agent-build-kit-track-20261028-133512`, one group:
1. `[agent-build-kit] [unit-test]` add `web/src/agui.test.ts` covering `readEvents` (split chunk, batched events,
   trailing event, multi-line `data:`, no body). No acceptance group, with the reason stated in `tasks.md`.

`abk check` and `abk tags` pass. Source candidate marked `[proposed — …]`; tracker entry added.

## Skipped for other repos / multi-repo
None.
