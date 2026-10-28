# Health 20261028-133244 — agent-build-kit

**Status:** PENDING RESOLUTION — only the already-tracked `grafana-url-env-test` issue remains; nothing new

## Findings

### logs-and-errors
- No run logs written in the last 24h; no tracebacks, rate-limit messages or fatals. Newest `runs/decisions.jsonl` entry is 27 Oct 02:51Z.
- Merges are still landing (#687–#693).
- `grafana-url-env-test` remains in flight (change `agent-build-kit-track-20261026-125001`); not re-checked.

### resource-usage
- Host was rebooted shortly before the check; containers had been up only seconds to minutes, so restart counts and trends are skewed. Disk 84% used (156G free), memory 23G available of 32G, load elevated but expected after boot. Not a finding for this project.
- `torrent-svc` sits in "Created" and never started — belongs to another project, not this repo.

### llm-observability
- Nothing applies: no LLM call sites of its own, no trace backend configured.

### pipeline-health
- Units (via `abk status`; `runs/units.json` no longer exists, state is in `runs/unit-graphs.sqlite`): 496 merged, 83 unplanned, 8 satisfied, 4 planned, 4 closed, 3 retired. None failed or held in the ordinary sense. Five unit merges in the last 24h, latest 07:15 today.
- The e2e-test split `acp` is held for a spent model budget with no deadline, while reported usage is low (session 3%, weekly 4%). Four units wait on it (`ui-chat-editing/6`, `dry-guidance/5`, `abk-web-ui/12`, `policy-check-asks-the-agents-own-matcher/6`). Worth a person's look; the cause is unconfirmed, so it is not raised as a candidate.
- The runtime-tagging change's unit `/17` is unplanned and parked; its groups moved to `/19`, so `abk retire` is a safe cleanup.
- 12 flaky tests, each with a fix change open.
- `runs/tick.json` shows tick #110 at 2026-10-27T00:59Z, yet commits keep landing; the subagent did not confirm whether ticks are stalled.

### secrets-scan
- No secrets in 28 commits from the last 24h (grep fallback, as gitleaks isn't installed; narrower than gitleaks).

## Actionable candidates for the next propose run

None this run
