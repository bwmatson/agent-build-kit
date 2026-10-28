# Recommend 20261028-133512 — agent-build-kit

First recommend run for this project. Tracker refresh: the one pending entry (`grafana-url-env-test`) is still in flight at `openspec/changes/agent-build-kit-track-20261026-125001/`, so it stays. No earlier recommend run exists, so there were no open candidates to re-check.

Limits: the test-coverage-gaps and technical-debt agents had no shell (no coverage tool, tests or git history), so their findings come from reading and searching only.

## Recommendations

### test-coverage-gaps
No meaningful zero-test area. `tests/` mirrors `src/` closely (over 1,300 test files). The gaps are narrow.

1. **The web SSE reader has no direct test (low to medium risk).** `readEvents` in `web/src/agui.ts` (lines 20-46) is the only parser of the chat and agent event stream. Existing tests (`web/src/agent.test.tsx`, `web/src/test/api.ts`) feed it one well-formed event per chunk. Nothing pins an event split across reads, several events in one read, a final event with no trailing blank line (lines 43-45), or multi-line `data:` joining. A regression would show up as dropped or garbled chat output, not a loud failure.
2. **Azure DevOps tracker read side has only happy-path coverage (low risk, new code).** In `src/agent_build_kit/trackers/azure_devops.py`, `children()` (lines 93-103) joins all child ids into one `ids=` request, and the service caps that at 200. Nothing tests a large fan-out or an empty page. `find_by_marker` doubles `'` in the WIQL tag (line 106), but no test passes a marker containing a quote. Revisit once the tracker has seen use.
3. **Web UI breadth is thinner than the Python side.** `App.tsx`, `useApi.ts` and `unitName.ts` have no test file of their own, and `usage.tsx` is exercised only through `pages.test.tsx`. Mostly routing and glue, so low priority.
4. Checked and covered: `pr_cmd`, `review_report`, `redact_history`, `replay_cmd`, `network_probe`, `git_output`, `review_order`, `trackers/report.standing`, and the Azure forge.

### technical-debt
One real item, and it is not a quick fix.

1. **`src/agent_build_kit/cli/pipeline.py` is 8,274 lines with 280 top-level definitions and does several unrelated jobs.** Beside the `cmd_*` handlers and `register` (line 7933), it holds at least six groups of pipeline logic that have nothing to do with argument parsing:
   - Tick round and admission: `run_round` (2113-2448, about 335 lines), `_may_build`, `_schedule` (4133-4325), the `_start_decision` and `_account_decision` family.
   - Wait-end, requeue and split handling: `requeue_wait_ended`, `split_held_units`, `release_split_held`, `wait_reasons`, `_planned_wait`, `requeue` (7672).
   - Slot and lane accounting: `slot_occupancy`, `_slot_*`, `_lane_*`.
   - About 25 diagnostic `_*_lines` builders (3665-4050).
   - Planning: `plan_all` (4971-5291, about 320 lines), digest and staleness helpers (5410-5611), the `replan` printers (7229-7540).
   - Stack, restack, poll and build: `build_restack_lane`, `build_stack_moves`, `poll_all`, `_build_unit` (6284-6568).

   The recommendation is a series of pure moves into `pipeline/` modules, one group per change. Because this is tick, requeue and wait-end code, AGENTS.md requires `merged` on the `Needs:` line between such changes, so the work serialises over several ticks. Do not do it as one change. A first move could be bounded, for example extracting the diagnostic line builders, after confirming their call sites.
2. Other long modules, watch only: `pipeline/wiring.py` (4,289 lines), `graph/nodes.py` (3,322), `pipeline/events.py` (2,509), `config.py` (2,379, a schema, so expected), `cli/doctor.py` (2,285), `pipeline/usage_guard.py` (2,241). None was read closely enough to show mixed jobs; `wiring.py` and `usage_guard.py` are the likeliest to be worth a look.
3. No TODO/FIXME/HACK debt (the only hit is a deliberate test marker string). The ecosystem-name and child-source allowlists only shrink and are test-enforced. A systematic duplicated-logic scan was not run, so this is not a clean bill of health.

### module-design
1. **"When did this unit merge" is re-derived in four modules (medium).** Each reads a unit's `history` list and searches it for entries whose `"state"` is merged, so callers know the history's dict shape and its `"at"` and `"state"` keys, which is leakage across the `StoredUnit` boundary:
   - `pipeline/demotion_triggers.py:79-81` `_merged_at`: `max()` of raw `"at"` strings, literal `"merged"`.
   - `pipeline/review_outcome_sweep.py:100-106` `_inside_horizon`: last merged stamp, literal `"merged"`, parsed with `fromisoformat`.
   - `pipeline/archive.py:97-108` `_merged_at(change, units)`: across every unit of a change, literal `"merged"`, next to bare `unit.state == "merged"` at lines 78 and 90.
   - `pipeline/unit_size.py:97-105` `_merged_at`: uses the `MERGED` constant (`pipeline/units.py:61`), parses safely, falls back to the epoch.

   The copies differ: string versus datetime comparison, max versus last entry, and different handling of an unparsable stamp. `StoredUnit` (`unit_store.py` around 450-475) already exposes `first_run_at` and `review_requested_at` via `_first_entry`; the "last entry into a state" case is missing. Suggested: a `merged_at` property returning `datetime | None`, then call it from the four sites. The tie-break and unparsable-stamp behaviour need a decision. Pipeline-module rule: add a `merged` edge if it follows another tick or graph change.
2. The roughly 25 `set_*` methods in `unit_store.py` (1207-1402) already share `_update` (line 1202); no change recommended.
3. Checked and not flagged: config access chains (callers go through `Installation` or `config.active()`) and thin wrappers (`host.this_host`, `planning_sync._one_line`).

### architecture-opportunities
Research topic this run: multi-agent / LLM agent orchestration patterns (topic 1, message broker, skipped as not applicable: the project has no broker).

1. **Real-agent behaviour of the ACP policy boundary has never been observed (medium risk, small effort).** `docs/agent-runtimes.md` has a section titled "What a real agent does with its deny list: not yet observed", and says ACP `process` coverage is "unverified against a real agent". The non-Claude policy story rests on this. A person with an ACP agent should run the documented probe once and record the result. This is a person-run step plus a doc edit, not a code change.
2. **One process still owns every build (larger, already designed).** `docs/designs/worker-design.md` says "Today one `abk tick` process owns every build" as threads, and describes a dispatcher plus detached workers. `cli/pipeline.py` still uses `ThreadPoolExecutor` scheduling (around line 4172) and no worker change is in `openspec/changes`. A long unit delays fresh kit code and configuration, which the AGENTS.md `merged`-edge rule works around. Recommend scheduling the first step (dispatcher and detached build worker) as a change; it is too large to bound.
3. **Concentration in `pipeline/wiring.py` (4,289 lines) and `runtimes/acp.py` (1,913 lines)** raises the cost of an agent-protocol change. No concrete coupling defect found, so watch only.
4. **MCP is deliberately closed off.** `runtimes/acp.py` passes `mcp_servers=[]` on every `new_session` (lines 1595, 1602, 1702). That is sound, but it means the kit cannot offer an agent a vetted read-only tool (unit state, spec lookup) over the protocol.

Research comparison: orchestrator-worker with isolated contexts is the established pattern ([Anthropic's multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)): explicit task mandates, plans kept in external memory, resumable checkpoints, outcome-based evaluation, and rainbow deployments so running agents finish on the old version (which matches the kit's tick-loads-code-once concern). Practitioner write-ups (secondary sources: [amux](https://amux.io/guides/ai-agent-orchestration-2026/), [dev.to](https://dev.to/nexmind_ai/enterprise-ai-agent-architecture-mcp-a2a-and-production-patterns-you-need-in-2026-3dif)) agree on git worktrees for parallel coding agents. The kit already matches this: a worktree and branch per unit, a mandate per prompt, checkpointed state, size ceilings and review tiers. The ACP [spec overview](https://agentclientprotocol.com/protocol/overview) lists `elicitation/create` as an optional client method; whether `runtimes/acp.py` answers it is unverified, and an unattended run should decline it rather than hang. A secondary source says some adapters (e.g. [pi-acp](https://github.com/victor-software-house/pi-acp)) do not request permission before tool execution, which is why item 1 matters: for such an agent only the process sandbox protects the kit. Nothing argues for adopting A2A or MCP here.

### cost-performance-opportunities
No findings. No trace backend or metrics store is configured, so the redundant-LLM-call and resource-trend checks could not run.

- The usage-limit check already caches: 243 of 244 lookups in `runs/usage-calls.jsonl` (2026-10-26T03:09Z to 2026-10-27T02:49Z) were cache hits; 10 reached the network at about 748 ms.
- OpenSpec runs through `npx`, which caches the package.
- State is `runs/unit-graphs.sqlite` at 2.2 MB with 496 merged units, so there is no query workload where scans matter. Individual queries were not inspected.
- Disk is at 84% (156 GB free) on a shared host and is not attributable to this repo; `runs/` is small.
- Unchecked: `gh` and `git` shell-out frequency in `pipeline/shell.py`, and a breakdown of `runs/usage-ledger.jsonl` (452 lines).

## Actionable candidates for the next propose run

1. [not-yet-actioned] Add `StoredUnit.merged_at` (a `datetime | None`, latest merged entry, unparsable stamps handled once) in `unit_store.py` and use it in `demotion_triggers.py`, `review_outcome_sweep.py`, `archive.py` and `unit_size.py`, removing the four private re-derivations and the bare `"merged"` literals. Needs a decision on tie-break and unparsable-stamp behaviour; give it a `merged` edge if it follows another tick or graph change.
2. [proposed — agent-build-kit-track-20261028-133512] Add `web/src/agui.test.ts` covering `readEvents` in `web/src/agui.ts`: an event split across two chunks, two events in one chunk, a trailing event with no blank line, a multi-line `data:` field, and a response with no body. Test only, no production change.
3. [not-yet-actioned] Check whether `runtimes/acp.py` answers `elicitation/create` with a decline so an unattended run cannot block; if it does not, add the decline and a unit test with the fake agent. The gap is unverified, so this candidate depends on the check.
