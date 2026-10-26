# Proposal

## Why

The internet went down for a while and two units failed for it: an implement step ended with `RuntimeError: claude exited 1: API Error: Can't reach
the API server — check your internet or DNS (EAI_AGAIN)`, after the agent had run for about five minutes and six minutes. Nothing was wrong with
either unit. A person had to requeue both.

The pipeline already tells "the code host is down" from "the unit failed": `HostUnavailable` parks the unit as `planned` with the cause
`host_unavailable`, records the step, backs off and resumes by itself. The network being down is the same kind of event and gets no such treatment:
the agent runtime turns a non-zero exit into `AgentResult(ok=False, error=...)`, the step raises a bare `RuntimeError`, and the unit is failed, which
only a person undoes. Every unit that tries to run during the outage fails the same way, one agent run at a time.

The same outage burned a change's planning attempts. A change was planned during it, and its planner call could not reach the API: each tick tried
once, the third failure recorded `{attempts: 3, ok: false}` — "given up until `tasks.md` changes or `abk replan` is run" — and a replan with the same
text succeeded at once afterwards. The three attempts were spent on the outage, not on the spec.

A provider outage while the internet works falls into the same hole twice: an HTTP failure (5xx, 529 overloaded) is not matched at all, and a probe that
says "reachable" when any host connects lets a weak "Can't reach the API server" with the API host down and the forge host up fail the unit.

## What Changes

- **A typed `NetworkUnavailable` and `ServiceUnavailable`**, raised by the agent runtime adapters: the first when a run ends on a DNS or connection
  failure (`EAI_AGAIN`, `ENOTFOUND`, `ENETUNREACH`, "Can't reach the API server", connection refused or timed out at connect); the second when the
  run's closing HTTP status is a 5xx or 529 (overloaded). Never for a 4xx, a 401 or 403, a 429 usage or rate limit, a model refusal or a tool failure.
- **A connectivity probe**, bounded and injected, with no model call, of the host the failing run called plus a control group (the forge hosts and a
  small configurable list of well-known hosts). It tells "the whole network is down" (the API host and the control group both fail) from "the
  provider, or the route to it, is down" (the API host fails and a control host connects) from "an ordinary failure" (the API host connects).
- **A unit stopped by an outage is parked, not failed:** `planned`, cause `network_unavailable` or `service_unavailable`, the step and the error text
  recorded, the thread, branch and saved feedback kept, no round of review, rework or checks charged, readmitted after the host-unavailable backoff,
  resumed at that step. A 5xx or 529 parks at most `limits.service_unavailable_attempts` times in a row (default 5) and then fails the unit.
- **A network pause:** the pause marker gains the kind `network`, written only for `network_unavailable`. While it stands, a tick starts no agent run;
  the first tick whose control group is reachable clears it. A `service_unavailable` is per-unit backoff only.
- **The status says so, differently:** `waiting for the network` and `waiting for the model service`, with the step and the time remaining.
- **A planning attempt is not spent on an outage:** the planner's call lets the typed error through; `plan_all` records the change as waiting
  (`waiting: network` or `service`, the time and the next try) with its attempt count unchanged, uses the same backoff steps, plans it again when
  the outage is over, and plans nothing while a network pause stands. `abk replan` and `abk status` say `waiting for the network` or `waiting for the
  model service`, never `failing N/M` or `given up` for it. An ordinary planner failure still counts, and its reason (the first line, bounded,
  redacted) is kept for any failure, building on the stored refusal reason of `edits-to-started-groups-need-no-plan`.
- **Left as it is:** the code-host handling, telemetry and gateway failures (non-fatal), and the usage reading's cache. Checks and tests that fail
  for the network are a named follow-up, not part of this change.

## Impact

- agent-build-kit: `runtimes/` (a classifier, the typed errors, both adapters), the new probe, `pipeline/unit_store.py` (the causes, the backoff and
  the status-attempt count), `pipeline/pause.py` (a kind), `cli/pipeline.py` (the handlers, readmission, the tick's skip and the status, `plan_all`, `_needs_planning`, `cmd_replan`, `_plan_state`), `config.py`
  (three limits), the docs (`unit-graph`, `architecture`, `agent-runtimes`, `configuration`), the `abk-pipeline` and `abk-config` skills, the changelog.
- Spec: `unit-scheduling` (adds six requirements, modifies three), `agent-runtime` (adds two).
