# Design

## What was checked, and where

Read-only against the agent-build-kit checkout; paths are under `src/agent_build_kit/`.

- The failure the units hit: both implement logs end `claude error`, then `failed, RuntimeError: claude exited 1: API Error: Can't reach the API
  server — check your internet or DNS (EAI_AGAIN)`, after 4m55s and 6m02s. The run is long because the CLI retries on its own before exiting.
- `runtimes/claude_code.py` `_finish`: `returncode < 0` raises `AgentInterrupted`; otherwise `agent_failure(ended, said)` (in
  `runtimes/claude_output.py`) returns a kind of `rate_limited`, `session_unavailable`, `other` or `none`. `rate_limited` raises
  `AgentRateLimited` (after reporting the call's spend through `on_result`); anything else with a non-zero exit returns
  `AgentResult(ok=False, error="claude exited N: <said>")`. `said` is the CLI's own words plus stderr, never the transcript.
- `pipeline/wiring.py` (the agent runner, ~line 375): `if not result.ok: raise RuntimeError(result.error)`. That is where the unit's
  step becomes a bare `RuntimeError`. `restack.py:659` and `planner.py:624` read `result.ok` the same way.
- `runtimes/acp.py`: failures come back as `AgentResult(ok=False, ...)` from several places (could not start, the connection ending, a
  failed turn) and as `AgentInterrupted` for a cancel. UNVERIFIED: the exact text or error a gateway-side connection failure produces; the
  classifier below is written for the claude runtime's words and the ACP path is covered by its signatures and a test, not by a captured failure.
- The code host: `forges/transport.py` `HostUnavailable`; `cli/pipeline.py`'s `except HostUnavailable` (~2974) records `PLANNED` with
  `Cause.HOST_UNAVAILABLE`; `_sent_back` readmits it when `backoff_remaining` is None; the build then sets it `RUNNING` again (~2902) and
  resumes at the recorded step. `pipeline/unit_store.py`: `HOST_BACKOFF` = 1, 2, 5, 10, 30 minutes by consecutive parking (`parked_attempts`,
  reset by a move to in review or failed); `backoff_remaining` returns None for any other cause. The status prints
  `waiting for the code host: <id> (<repo>) at <step>, Ns remain — <note>`.
- `pipeline/pause.py`: one marker file, `PauseKind = Literal["usage", "rate_limit"]`. A `usage` pause is re-asked every tick and cleared by
  the first tick the guard allows; a `rate_limit` pause is honoured to its deadline.
- `pipeline/units.py` `in_progress`: a planned unit counts when it has work (a branch, a pull request, a pushed or approved commit) and is not
  `blocked` (waiting on another unit). A unit parked for the host has a branch, so it keeps its place.
- `pipeline/usage_guard.py` and `usage_cache`: when the usage endpoint cannot be read, readings come from `~/.claude.json`'s cache and the
  adaptive cache file, labelled `source="cache"`. That is why the status showed cached readings during the outage; it is the intended
  degradation and is left alone.

UNVERIFIED: how the graph and the web page draw a unit parked for the code host (a planned unit, probably by its cause label). The network cause
is made to appear in the same places the host cause does, whatever they are; the builder reads them and follows.

## Recognising an outage

Evidence, never a model call: a signature in the run's words, an HTTP status in its closing event, and a probe.

**What carries an HTTP status (read from `runtimes/claude_output.py`, `pipeline/claude_stream.py`, `runtimes/claude_code.py` `_finish`).** The
claude runtime runs `claude` with stream-json output and reads the closing `result` event as a `ResultEvent`, which has a field
`api_error_status: int | None`: "the HTTP status of the API error that ended the run, `null` on a clean one". `agent_failure` already uses it for
429 (`RATE_LIMIT_STATUS`) and nothing else. The text a failed run carries is `own_words` (the event's `result` text plus its `errors`) and stderr,
which `_finish` joins into `claude exited N: <said>`; the logged outage text is of that form. So there are two carriers: the structured
`api_error_status`, and the words. UNVERIFIED: that the CLI sets `api_error_status` to 500..599 or 529 once its own multi-minute retries are
spent (the fixtures in `tests/fixtures/external/claude/` show it for 429 only); UNVERIFIED: whether a final 529 is worded `API Error: 529 ...`,
`overloaded_error` or both. The rule therefore reads the structured status first and, when it is `null`, the words for `API Error: <3 digits>`
and the token `overloaded_error` only; when neither says a status, the failure carries none, rule (2) does not apply, and the run is judged by the
signatures and the probe below. The ACP runtime has no closing event with a status; UNVERIFIED what its failed result carries, so the status
path is the claude runtime's only, and an ACP provider outage is caught by the probe path alone.

**Signatures** (`runtimes/network.py`, one function, `network_failure(text)`, returning `strong`, `weak` or none, with the table as data):

- strong, a name or route that cannot be resolved or reached: `EAI_AGAIN`, `ENOTFOUND`, `ENETUNREACH`, `EHOSTUNREACH`, "getaddrinfo",
  "temporary failure in name resolution", "network is unreachable";
- weak, which a live network can also produce: "Can't reach the API server" without a strong word, `ECONNREFUSED`, `ETIMEDOUT`, "connect timed
  out", "connection reset" while connecting.
- never: a failure that carries an HTTP status is not matched, even if a signature word appears in it. (Such a status belongs to rule (2) or, for a
  4xx, 401/403, 429, to the ordinary path.) A model refusal, a usage limit, a permission or tool failure is never matched.

**The probe** (`pipeline/network_probe.py`, an injected callable in the way `usage_guard`'s readers are, taking the failing run's API host and
returning which of the two groups had a host that connected). It checks two groups with a DNS lookup then a TCP connect, bounded by
`limits.network_probe_timeout_seconds` (new, default 5, a positive whole number, checked at load) per host, sending no request body, so it spends
nothing and needs no key:

- **the failed host:** the API host of the runtime whose run failed. `ClaudeCodeRuntime` knows its own. UNVERIFIED: the ACP runtime cannot name its
  gateway host from its command line; with no host of its own it has no "failed host", so the probe cannot run for it and its failures take the
  strong-signature shortcut and the ordinary path only. A later change can let it name one.
- **the control group:** the forge host(s) from the workspace's forge config plus `limits.network_control_hosts`, a list of host names (new;
  default `["one.one.one.one", "dns.google"]`; each a bare host name checked at load, port 443). The default is two public resolvers' names run by
  two different, large operators: stable, answering TCP 443, independent of each other and of any model provider, and resolved through the same
  resolver the API host needs, so a broken resolver shows in both groups. It is a setting because an installation behind a proxy or on a restricted
  network knows better which hosts it can always reach; the list adds to the forge hosts and never removes them. An empty list is allowed.

The outcomes, in a function `classify_reachability(...)` with the probe injected:

| API host | control group | meaning | parks as |
|---|---|---|---|
| fails | fails | the whole network is down | `network_unavailable` |
| fails | any host connects | the provider, or the route to it, is down | `service_unavailable` |
| connects | (any) | an ordinary failure | fails the unit, unless rule (2) applies |
| the probe cannot run or errors; or the control group is empty | | undecidable | counts as "API host reachable": fails the unit, unless rule (2) applies |

A probe that errors counts as "API host reachable", so a bug in the probe never parks a unit. This is the false-positive guard, kept.

**Rule (1), the network and the provider.** A strong signature parks the unit as `network_unavailable` on its own evidence: the agent's own run
just saw a name fail, and by the time the run returns (minutes later) the probe may already succeed, so asking it would turn a real outage that
ended into a failure. A weak signature parks only by the table: both groups failing is `network_unavailable`, the API host failing with a control
host connecting is `service_unavailable`, and the API host connecting leaves an ordinary failure. This is what makes "Can't reach the API server"
with the API host down and the forge host up a `service_unavailable` and no longer a failed unit. Residual: a strong signature that only the API
host's name produced (a DNS record gone for that host alone) parks as `network_unavailable` and writes a `network` marker; the next tick's probe
finds the control group up and clears it, so the marker costs one tick, and the unit's own retry then meets the weak or strong text again and parks
again with a growing backoff.

**Rule (2), a degraded service by HTTP status.** When a failed claude run's closing status is 500..599 (529 included), after the CLI's own
retries, the unit parks as `service_unavailable` without asking the probe: a status is an answer from the provider, so the network and the route
work, and the probe could only say "reachable". The park is bounded: the unit records a count of consecutive status parkings
(`service_attempts`), and at `limits.service_unavailable_attempts` (new, default 5, a positive whole number, checked at load) the next such
failure fails the unit with its error text, because a persistent 5xx can be a real fault (a request the provider cannot serve, a model that is
gone). The count resets when the unit moves to in review or failed and when a step completes, as `parked_attempts` does. Left as failures exactly
as today: any 4xx, 401 and 403, a 429 (its own path: `AgentRateLimited` and the usage pause), a model refusal, a permission or tool failure, and
a run whose status cannot be read.

**What is capped and what is not.** Only the status path is capped. The probe path (`network_unavailable` and the probe's `service_unavailable`) is
uncapped, as the network path is: the evidence is a connection that fails right now, which a real fault in the unit does not produce. Residual
risk, said plainly: a resolver that is misconfigured for good gives `EAI_AGAIN` on every run, and an API host that is blocked for good gives a weak
signature with a control host up; either parks the unit every time, backs off to the 30-minute ceiling and never fails. The status shows the parking
count and the note, so it is visible, but nothing stops it. UNVERIFIED whether that needs a cap; none is added, and a cap is a follow-up. An
hours-long provider outage keeps a unit parked for as long as it lasts if the CLI's words carry no status, and fails the unit after five status
parkings (about 48 minutes of backoff plus the runs) if they do; a person requeues such a unit.

## The typed errors

`NetworkUnavailable(RuntimeError)` and `ServiceUnavailable(RuntimeError)` beside `AgentRateLimited` in `runtimes/base.py`. The first names the
failing endpoint when the text does, carries the CLI's words as its message, the signature's strength and the API host that was called; the
second carries the status and the words. The names match `HostUnavailable`. `claude_code._finish` raises them where it raises `AgentRateLimited`
(and reports the call's spend through `on_result` first, the same way): `ServiceUnavailable` for a status in range, `NetworkUnavailable` for a
signature (strong or weak, the handler applies the table to the weak one, since the probe belongs to the pipeline and not to a runtime); `acp`
raises `NetworkUnavailable` where it builds a failed result whose text matches. `AgentResult(ok=False)` stays what every other failure returns, so
no caller's contract changes. A call site that catches `RuntimeError` broadly would catch these too; UNVERIFIED which do (the planner's and
restack's calls read `result.ok`, not an exception, and are now reached by the typed errors before they read it). The tick's step handler catches
them before its generic `except Exception`, as it does `HostUnavailable`, so the unit is parked and not failed whichever step raised them. The
agent steps, tier 2's agent calls and the planner's call all go through the same adapters.

The code-host handling does not change: `HostUnavailable` still parks with `host_unavailable`. A step can see several in a row (a push after an
outage); each parks under its own cause.

## The unit: parked, not failed

`Cause.NETWORK_UNAVAILABLE = "network_unavailable"` and `Cause.SERVICE_UNAVAILABLE = "service_unavailable"`. The handler writes `PLANNED` with the
cause and the error text as the note, after the step has been recorded, exactly as the host handler does; `step` is kept for both causes as for the
host one, and `parked_attempts` counts all three. Nothing about the unit's branch, thread, session, saved feedback or approved commit is touched, so:

- it resumes at the step that stopped, in the mode it was in: a fresh step starts again (default resume, as the host case does), and a step that
  was continuing a session continues it, the session being on the thread;
- no review round, rework round or check round is charged: those are counted when a round completes, and the step never completed;
- a step that had made edits before the run died leaves them on disk; the existing resume path for a step stopped part-way (an interrupted
  run) handles that, and this change adds no handling of its own. UNVERIFIED: that a half-finished agent step resumes cleanly from the
  worktree; `AgentInterrupted` takes the same route and is the precedent.

**Backoff.** One table, not two: `HOST_BACKOFF` is renamed to a neutral `PARK_BACKOFF` (1, 2, 5, 10, 30 minutes, ceiling 30), and
`backoff_remaining` applies it to all three causes. The numbers are unchanged for the host. No new setting for the numbers. A first parking waits
a minute and the tenth waits thirty, so a long outage costs a probe and no agent run every half hour per unit, and a short one costs a minute.

**The slot.** A parked unit keeps its place, as a host-parked one does, for all three causes: it has work, is not `blocked` (it waits on no unit)
and `in_progress` counts it. This change does not free it. `blocked-units-free-their-slot` and
`failed-units-waiting-on-a-prerequisite-free-their-slot` free places for units that wait on other units, which a parked unit does not; freeing it
here would let new units start into an outage that cannot run them. The changes are independent and need no `Needs:`.

**Readmission.** `_sent_back` and its callers read the causes as they read `host_unavailable`: readmitted when `backoff_remaining` is None. At
readmission the unit is `RUNNING` again before its node runs, as for the host. Readmitting does not itself probe: if the outage is still on, the
step fails again, parks again and the backoff grows.

**Display.** The two causes read differently wherever a cause is shown. The status prints
`waiting for the network: <id> (<repo>) at <step>, Ns remain — <note>` for `network_unavailable` and
`waiting for the model service: <id> (<repo>) at <step>, Ns remain — <note>` for `service_unavailable`, beside the code-host line. The graph and
the unit page label a planned unit by its cause; the two causes get the two labels `waiting for the network` and `waiting for the model service`.
`docs/unit-graph.md` names both. UNVERIFIED (as before): how the graph and the web page draw a cause today; the builder reads them and follows.

## During an outage: a pause marker for the network, none for the provider

Per-unit backoff alone leaves every other ready unit free to start an agent run into a network outage and fail it five minutes later, then park;
with five slots that is five wasted runs per backoff, and a usage-guard decision spent on each. A pause stops that.

**Recommendation: extend the pause marker, for `network_unavailable` only.** `PauseKind` gains `"network"`. `pause.py`'s own model fits: a pause is
global, visible (a file and a run-log line) and ended by what changed rather than by a deadline. A `network` pause behaves like `usage`, not like
`rate_limit`:

- it is written, with a reason ("network unreachable during <unit>") and an `until` of now plus the first backoff, when a unit is parked as
  `network_unavailable`; a pause already standing is not replaced by a later `until`. `service_unavailable` never writes or reads it;
- a tick with a `network` marker asks the probe's control group first. If a control host connects the marker is cleared and the tick goes on as
  normal; if none does the tick starts no agent run and says so once in its log, naming the marker. The tick has no failing API host, so only the
  control group is asked;
- the probe is the only way it ends: no deadline is honoured, because the outage ends when the network does, and the 1-minute-and-up backoff of the
  parked units is a floor on each unit's own retry, not on the pause.

Per-unit backoff stays as well, because it is what readmits a parked unit at its own pace and covers a pause cleared by hand. What a pause does
and does not stop: it stops starting agent runs. UNVERIFIED whether the tick's other work (opening pull requests, polling the host, merging
verification) is gated by a pause today; the builder reads the tick's gate and the network pause stops what a `usage` pause stops and nothing
more, since those steps need the network too but fail through `HostUnavailable` already.

**A tick and a standing `service_unavailable`.** Nothing special beyond the unit's own backoff: a tick keeps starting new agent runs. Why: a
provider outage is rarely total (a 529 is often one model or a burst; a blocked API host affects the runs of one runtime), and the only authority
on whether a run will be served is a model call, which this change excludes; a global stop on a guess would also hold back units that would run.
Cost: each ready unit can start one run into an outage and park, at most the slot count per backoff round, each costing the CLI's multi-minute
retry. Accepted; a follow-up `a-provider-outage-pauses-agent-runs` could add a provider pause once the cost shows. The pause marker is therefore
not extended for it, and a provider outage does not stop units or ticks that need no agent run.

The alternative for the network, per-unit backoff only, is simpler and changes `pause.py` not at all, and is rejected for the wasted runs above.
It is the fallback if the pause group is not built: groups 1 and 2 stand on their own.

## Planning is a model call too: an outage is not an attempt

**What was seen.** A change committed in the early afternoon reached `runs/planned.json` as `{attempts: 3, ok: false}` — "given up until `tasks.md`
changes or `abk replan` is run" — during the outage: the planner's model call could not reach the API, each tick tried once and three ticks spent the
three attempts. A replan with the same text planned it on the first try. The attempts were spent on the outage.

**What was checked** (read-only against the agent-build-kit checkout, `src/agent_build_kit/`; line numbers are those of the checkout read):

- `pipeline/planner.py:615-630` `_ask`: runs the active runtime with no worktree and no tools; `if not result.ok: raise PlannerError(f"the graph
  call failed: {result.error}")`. So a failed graph call is a `PlannerError` and reads like a refusal of the plan; the words are the runtime's. A
  typed error raised inside `runtime.run` is not caught there: once the runtimes raise `NetworkUnavailable` and `ServiceUnavailable` (groups 1 and 2)
  it passes through `_ask` and `plan_round` untouched, which is what is wanted. The planner needs no change.
- `cli/pipeline.py` `plan_all` (2173): per change, `record = {} if force else planned.get(change)`; `_plan_is_current` (919) skips a record whose hash
  is the file's and which is `ok` or has `attempts >= max_plan_attempts` (`config.py:316`, 3). The planner call sits in a `try`; `except
  GroupTooLarge` spends every attempt at once (a fault of the text); `except Exception` (~2300) writes `attempts = previous (if the hash matches) + 1`,
  `ok: False`, adds `_refusal(error)` for a `PlannerError` only, logs "planning <change> failed (n/3) — giving up until tasks.md changes or abk replan is run", and returns `PlanResult(status="failed")`. That block is where an outage becomes an attempt, and a typed outage error lands in it.
- `_needs_planning` (927) answers whether a round has a change to plan, so `_may_build` (~1012) asks the usage guard only when it does; `tick` runs
  `plan_all` only when `may == "yes"` (~1142, "planning spends a model call, so it stays behind the guard"). A `usage` or `rate_limit` pause therefore
  already skips planning. A `network` pause (group 3) is a third kind read at the same gate, so the same gate must skip planning under it.
- `cmd_replan` (3292) and `_plan_state` (3391): a bare `abk replan` prints `<change>: planned | never planned | failing n/3 | given up` with the stored
  `reason` after it; `--failed` selects every change whose record has `ok is False`; `--forget` removes the records; a selected change is planned with
  `force=True`, which ignores the record and counts attempts from none. `abk status` has no plan line today: UNVERIFIED where it would print one; it
  prints the unit waits, and the builder adds the planning wait beside them.
- `_refusal` (2167) and `record_plans` (2479): the stored `reason` is `str(error)` of a `PlannerError`, whole and unredacted, and it is stored for no
  other exception. `redaction.py:195` `redact_text(text, *, where)` exists and `log` uses it (`cli/pipeline.py:244`); `record_plans` does not.
  The earlier worry that the record keeps no reason is therefore half true: the merged `edits-to-started-groups-need-no-plan` group 2 (commit
  76e4f31, archived) stores it for a `PlannerError`, which covers `the graph call failed: ...` but not any other exception, with no bound and no redaction.

**Recommendation: a typed outage is a wait, not an attempt.** In `plan_all`, before the generic `except Exception`, catch `NetworkUnavailable` and
`ServiceUnavailable`, classify them as a unit's handler does (a strong signature or a status is taken as it is; a weak signature goes through the
probe table of "Recognising an outage", with the runtime's own API host and the control group), and write a wait instead of an attempt. A weak
signature with the API host reachable, or a probe that errors, is an ordinary failure and counts, the same false-positive guard. Justification:
planning shares the runtime, the evidence and the cost of a wrong guess with a unit's run, so one classification is used for both and the two cannot
disagree; the alternative of a fixed longer retry would leave the three-attempts rule to the clock and still fail on a longer outage.
UNVERIFIED: where the shared classification function sits (the builder lifts it out of the step handler of group 1 so both read it; its name is the
builder's); that a replan or a tick can tell the active runtime's API host for the probe (the claude runtime knows its own, the ACP runtime has none,
so for it a weak signature stays an ordinary failure and only a strong one or a status waits, as for units).

**The plan record.** A wait is a field set on the change's record in `planned.json`, beside `hash`, `attempts`, `ok`, `reason`:

```
{"hash": "<digest>", "attempts": 1, "ok": false,
 "waiting": "network" | "service", "waits": 3, "since": "<iso>", "until": "<iso>", "reason": "<first line, bounded>"}
```

- `attempts` is what it was before the wait, whether the wait is the first or the fifth in a row; a record that had none keeps 0. Three waits in a
  row leave it where it was. `ok` stays False so `--failed` and the status see a plan that has not worked.
- `waits` counts consecutive waits for this hash, `since` is the first of them, `until` is now plus the step of `PARK_BACKOFF` (1, 2, 5, 10, 30
  minutes by `waits`, the table group 1 renames, shared by the three unit causes and this). It is keyed by the change's own record, which is the
  unit of planning, so there is nothing to park: no unit exists yet, no unit is touched, and nothing is stored in `units.json`. The hash keys the
  rest: an edit of `tasks.md` starts the record over, as it does attempts.
- `waiting` is cleared, with `waits`, `since` and `until`, by a successful plan, by an ordinary failure (which sets `attempts + 1` and its reason as
  today), by an edit of `tasks.md`, by `abk replan --forget`, and by a replan that wins; `attempts` is not changed by clearing.
- A `service` wait is bounded as a unit's is: a ServiceUnavailable by status counts in `waits`, and once `waits` reaches
  `limits.service_unavailable_attempts` the next such failure is recorded as an ordinary failed attempt (with its reason) and the wait ends; the
  probe-detected service outage is uncapped, as for units. A `network` wait is uncapped.

**Due.** `_plan_is_current` stays as it is (hash and `ok` or attempts spent). A new check, `_plan_waiting(record, now)`, says a record is waiting
and not yet due; `plan_all` skips such a change (`PlanResult(status="skipped")`, as for a current plan) and `_needs_planning` does not count it, so
a round whose only candidates wait asks the usage guard for nothing. A wait is due when `until` has passed. A `network` wait is due the tick the
network pause clears (a control host connects), whatever `until`, so planning resumes with the rest of the work and not up to thirty minutes later.
`abk replan` ignores the wait: the person asked for a plan now, one model call is made, and a still-down network records a wait again with
`waits` starting from 1.

**A tick under a network pause plans nothing.** The tick's planning step already sits behind the gate that skips builds under a `usage` pause. The
`network` pause of group 3 is read at that same gate, so planning is skipped with the agent runs and costs no model call; a wait is therefore not
retried every tick of an outage, and a confirmed outage ends the tick's work for planning in one place. A planning wait writes the `network` pause
exactly as a unit parked for the network does (same reason format, "network unreachable while planning <change>", same rules about not replacing a
standing one with a later `until`) and a `service` wait writes none. The consequence, said plainly: an outage seen first by the planner stops agent
runs too, which is right, the evidence is the same.

**Display.** The `abk replan` listing and `abk status` say the change waits, with the time of the next try and the attempts as they stand:

```
<change>: waiting for the network since 16:20, next try 16:25 (attempts 1/3, not used)
<change>: waiting for the model service since 16:20, next try 16:25 (attempts 1/3, not used)
```

never `failing n/3` or `given up` for a record with `waiting`. A record that was spent before this exists keeps showing `given up`. `abk replan
<change>` for a change that meets the outage again prints `<change>: waiting for the network — no attempt used; next try HH:MM` where it printed `the
plan failed — see above`, and exits 1 as for any plan that did not happen. The wait is shown by cause, the same two phrases the unit lines use.

**The reason, for every failure.** The stored `reason` of the merged `edits-to-started-groups-need-no-plan` is the one field; it is extended, not
joined by a second one (the earlier outline called it `last_error`; the merged name is kept so a record has one). Every failed attempt and every wait
stores `reason`: for a `PlannerError` what `_refusal` stores today, for any other exception `<ExceptionName>: <message>`, in each case the first
line, cut to 300 characters, passed through `redact_text` (`where="plan record"`) before `record_plans` writes it, because a runtime's words can echo
a token or a path. The `units` list of `_refusal` stays. The bare `abk replan` listing shows it beside `failing n/3`, `given up` and `waiting`. The two
changes fit like this: the refusal reason (a plan the planner returned and the checks refused) is theirs and is unchanged; this change makes the same
field reliable for the failures that raised instead of returning (a call that failed, a parse that raised, an unexpected exception), bounds and
redacts both, and leaves the `units` list and the clearing on success as they are. Nothing of theirs is duplicated. UNVERIFIED: that `redact_text`
is safe to call on a long text with the active set unloaded; it returns a notice when the set raises (`redaction.py:195`), and the reason then reads as
that notice.

**Units already given up by an outage.** No migration, no scan of old records: a record `{attempts: 3, ok: false}` has no reason that says an outage
and is indistinguishable from a real one. `abk replan --failed` exists (`cmd_replan`, the `--failed` branch selects each change whose record has `ok
is False`) and plans exactly those again; the `given up` text names it: "given up: run abk replan --failed, or edit tasks.md". The existing
requirement that the failing-plan message names `abk replan` is extended to say which form.

**Left out, named.** A 429 usage or rate limit while planning takes the `except Exception` path and counts as an attempt today (UNVERIFIED whether
the guard makes that rare: it is asked before every planning round). It has its own pause and path and is not changed here; if it shows up, a
follow-up gives it the same wait.

## Tier 2 and checks: named follow-up, not built here

The ask is to retry a check or test whose failure output matches an outage signature once the probe says the outage ended, and not to charge it
to the unit. Not done here, because:

- the signatures differ per tool (`uv`/`pip` index failures, `npm` `ENOTFOUND` and `ECONNRESET`, `curl`, a test's own request errors) and
  the output of a test is the unit's own words as often as the tool's: a test that asserts on a connection error would match;
- the retry changes what a check result means, which touches `check_failures.py`, `check_runner.py` and the tier 2 runner's three-run rules, and
  needs more than one group;
- UNVERIFIED: whether the tier 1 gate's checks already run offline-safe (no fetch) in the planning repo; nothing was read to confirm.

The follow-up is named `outage-during-checks-is-not-charged`: a failure is retried once, uncharged, only when a signature matches, the probe was
down at the failure and is up at the retry; a check that fails again is then charged normally. Until it exists, a check that fails because a package
index was unreachable fails the unit's round for the environment's reason, as today. Tier 2 runs that call real agents are covered by the typed
error, since they reach agents through the same adapters; a tier 2 run that calls a live endpoint directly is not.

## What is left alone

- Telemetry and the <redacted> gateway's own endpoints: their failures stay non-fatal and never raise `NetworkUnavailable`; nothing in them is read as an
  outage.
- The usage reading's cache: offline it keeps answering from the cache, labelled `cache`. A cache reading is a usage decision and is not a
  connectivity signal.
- `HostUnavailable`, its backoff numbers and its parking.
- Retries inside the CLI itself, which are why the run lasts minutes; this change does not shorten them. UNVERIFIED whether the CLI exposes a
  setting that would shorten them.

## Units already failed by an outage

No migration. The two units failed before this exists were requeued by hand and ran. A unit still `failed` with `API Error: Can't reach the API
server` in its note stays failed, and a person requeues it; nothing scans old notes.

## Docs

`docs/architecture.md` (the planning section, ~lines 106-125: the wait and the stored reason), `docs/cli.md` (`abk replan`, the listing and the exit), the `abk-pipeline` skill (the plan states), and, as below, `docs/unit-graph.md` (the host-unavailable paragraph, ~line 481, gains both causes and their labels), `docs/architecture.md` (~lines 518 and 577: the
readmitted causes, the pause kinds), `docs/agent-runtimes.md` (the typed errors, the signatures and the status rule), `docs/configuration.md` (the
probe timeout, the control hosts and the status attempts), the `abk-pipeline` skill (the `planned` row's cause list, the pause section) and the `abk-config` skill's `limits:` block (all three limits), and one
changelog bullet under `## Unreleased`.

## Related changes

`blocked-units-free-their-slot` and `failed-units-waiting-on-a-prerequisite-free-their-slot`: independent, see "The slot". `edits-to-started-groups-need-no-plan` (merged): group 2's stored refusal reason is built on, see "Planning is a model call too". `tier2-lock-wait-is-configurable`
adds a limit beside the one added here and shares no code.
