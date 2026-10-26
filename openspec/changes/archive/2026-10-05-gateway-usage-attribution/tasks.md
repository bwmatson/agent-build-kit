# Tasks

Acceptance: none — a client behind a seam, tested with a fake gateway; the
accounting chain's end-to-end check is in `usage-report`.

## 1. [agent-build-kit] [tier1] Exact usage from the gateway's own records

Done when a gateway-backed agent run records the totals the gateway logged for its
own key, with source `gateway`, and every failure falls back without failing the run.

- [x] 1.1 Check against the runtime in use that an ACP agent reads its gateway key
      from its environment at start, and note the result in the design.
- [x] 1.2 Test: with a fake gateway, a run mints a key aliased with the unit, node
      and round, passes it in the agent's environment, reads that key's totals
      afterwards, records them with source `gateway` and revokes the key even when
      the run fails.
- [x] 1.3 Test: two concurrent runs get different keys and each records only its own
      totals.
- [x] 1.4 Test: no settings means no call to any gateway; an unreachable gateway or a
      refused mint falls back with one warning and the run is unaffected.
- [x] 1.5 Test: where the agent also reports usage, both are kept and the difference
      is available to the report.
- [x] 1.6 Add the `UsageSource` seam, the gateway client, the two settings, and the
      wiring into the agent step.
- [x] 1.7 Document the settings in `docs/configuration.md` and the `abk-config`
      skill, `docs/agent-runtimes.md`, and the changelog.
