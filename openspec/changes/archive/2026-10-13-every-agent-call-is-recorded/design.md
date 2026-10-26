# Design

Every site below was read in `agent-build-kit` at `origin/main` (c2a76e1). A line is cited as
`file:line`. Where the first sketch was wrong, the correction is in "Corrections".

## The audit

Every construction of `AgentRequest(` in `src/`, and every direct call of a runtime's `run`, with whether
it sets `on_result` (what writes a ledger row) or `on_record` (what writes transcript events, which is
not a ledger row):

| Site | What it is | `on_result` | `on_record` | Ledger row before | Node after |
|---|---|---|---|---|---|
| `pipeline/wiring.py:334` (`build_run`'s `run_agent`) | every unit step | `partial(on_result, ...)` when the step passes one (`wiring.py:340`; the unit nodes pass `self._recorder`, `graph/nodes.py:605,644,697`) | the unit's transcript (`wiring.py:363`) | yes, written at `graph/nodes.py:777-799` | `tests`, `implement`, `review`, `rework`, `fix_checks`, `adapt` (unchanged) |
| `pipeline/restack.py:651` (`claude_resolver`; run at `:662`) | the conflict resolver, called from `move_branch_onto` at `:316` | no | no | no | `restack` |
| `pipeline/planner.py:664` (`_ask`) | the planning graph call, one per `plan_round` (`cli/pipeline.py:2436`) | no | no | no | `plan` |
| `tracks/runner.py:402` (`phase_request`; run at `:642`) | a track phase: health, improve, recommend, propose | no | no (`keep_record=True` keeps the raw output file only) | no | `track_health`, `track_improve`, `track_recommend`, `track_propose` |
| `init/research.py:127` (run at `:132`) | init's research of a language | no | no | no | `init_research` |
| `init/propose.py:309` (`write_change`; run at `:308`) | init's and the propose track's proposal, once and once more to repair | no | no | no | `init_propose` |
| `runtimes/acp.py:1734` (`_probe`, via `_drive`) | the policy probe prompt | no, and `_drive` is called directly so `_call`'s `on_result` (`acp.py:1315`) never runs for it | no | no | `policy_probe` |
| `serve/chat.py:513` (`request`; run at `:443` and `:821`) | a chat turn, and the attach flow's `fix` turn | no (`callbacks` holds `on_record`, `on_session`, `on_permission`, `chat.py:437-439`) | yes, the transcript and the live stream | no | `chat`, `chat_commit` |
| `runtimes/claude_code.py:167-173` (`refresh_login`) | `claude -p "Reply with OK"` on the smallest model, to refresh a login before a usage read; no `AgentRequest` | not applicable; output discarded | not applicable | no | `login_refresh` |

Chat writes no ledger row: `UsageRecord(` is constructed in one place only, `graph/nodes.py:777`, and
`serve/chat.py` has no reference to it or to `record_call`. The calls `usage_guard.py` makes to
`record_call` (`:615`, `:694`, `:1258`) write the usage-read calls file, not the agent ledger, and send no prompt. The
runtimes' `list_models` and `_declares_loading` open a connection and send no prompt, so they spend nothing and stay out.

## The helper

`pipeline/call_record.py`, new, holds the one writer of an agent row:

- `call_recorder(node, *, unit="", change="", repo="", tier="", round=0, resumed=False, say, gateway=None)`
  returns the callback a runtime calls with the finished `AgentResult` (the shape of `AgentRequest.on_result`
  once `role`, `model` and `runtime` are bound). It builds the `UsageRecord`, working out the cost and
  the session's cumulative baseline, and writes it with `record_call` (`usage_ledger.py`), which never raises.
- `recorded(request, runtime, *, node, ...)` returns `request` with `on_result` set to a recorder bound to
  `request.role`, `request.model` and `runtime.name`; a callback the request already had is called first.
- The cost derivation (`_baseline`, `_cost` of the unit node, `graph/nodes.py:802-886`) moves into this module
  as functions of the result and the ledger, so the unit steps' recorder calls the same code. A test over the
  unit steps' rows before and after proves the rows are byte-identical for the same results.

The row's schema is unchanged: `kind`, `at`, `unit`, `node`, `round`, `change`, `repo`, `tier`, `role`,
`model`, `runtime`, `session_id`, `resumed`, the four token counts, `cost`, `context`, `turns`, `duration_ms`,
`usage_source`, `reported`, `outcome`. A reader written before this change reads these rows, because every
field already has a default and `extra="ignore"`.

### What each node records

| Node | `unit` | `change` | `repo` | `tier` | `role` | `model` | `round` |
|---|---|---|---|---|---|---|---|
| `restack` | the unit being moved (`ConflictContext.moving_unit`) | its change when the caller knows it | its repo when known | blank | `generic` | the request's, null when the runtime chooses | 0 |
| `plan` | blank | the change planned, as `plan_round` has it (the first of `changes`) | blank | blank | `generic` | null | 0 |
| `track_<phase>` | blank | the change a propose run writes, from `planning_change_dir` | the project the phase runs for | blank | `generic` | `tracks.model` | 0 |
| `init_research` | blank | blank | blank | blank | `generic` | null | 0 |
| `init_propose` | blank | the change written | the repo proposed for | blank | `generic` | null | 0 |
| `policy_probe` | blank | blank | blank | blank | `generic` | null | 0 |
| `login_refresh` | blank | blank | blank | blank | `generic` | `haiku`, as the call names it | 0 |
| `chat` | the unit the session is attached to, else blank | its change | its repo | its tier | `generic` | the model the turn names | 0 |
| `chat_commit` | the unit being committed | its change | its repo | its tier | `generic` | the recorded builder's model | 0 |

`role` comes from `AgentRequest.role` (`implement`, `review`, `rework_review`, `generic`; `base.py:41`). The `models:`
roles select a model for the unit graph's steps only; none of the new sites has one of those roles, so each records
`generic`, which is what the request carries. A figure a call does not have is recorded as absent, never zero, exactly
as for the unit steps; `login_refresh` discards the agent's output, so its row has no tokens or cost, source `none`,
the wall time of the call as `duration_ms`, and `outcome` from the exit status.

`change` and `repo` are filled when the caller knows them; the report already fills a missing change and repo from the
unit store when the unit is known (`usage_report.py:407-413`), so a caller that knows only the unit id is enough.

The outcome is `ok` or `failed` as for the unit steps. A call that raises before returning (a refusal for
the usage limit, a killed process) writes no row, as today for the unit steps, because no result exists; the
runtimes call `on_result` with the failed result before they raise (`acp.py:1315`, `claude_code.py:303,347`), which
is what the helper records.

## How the reader treats a call with no unit, or no round

The reader keeps one record per `(unit, node, round)`, replacing a re-run and adding a resumed call
(`usage_ledger.py` `grouped_records`). That is right for a unit's node, which a kill can re-run, and wrong for the new nodes:
two resolver calls for one unit, every `plan`, and every chat turn share a key, so each would replace the one before and the
ledger would again lose spend.

Rule: a record whose node is not one of the unit graph's call nodes (`tests`, `implement`, `review`, `rework`,
`fix_checks`, `adapt`) is its own record, keyed by its `at` as a call with no session id is today, whatever its session id.
Each row of a new node is a call; none of them is re-run by a kill, because none is a node a unit resumes. The cost
baseline of a call in a session another call started still comes from the ledger (`session_cumulative`), so a chat turn
that continues a session records its own incremental figure.

The rule changes no existing record: a ledger written before holds only unit-graph nodes. Two readers need a second line:

- The usage estimate and its calibration count distinct unit ids on rows since a reading
  (`usage_guard.py:1077-1083`, `units_since`). A blank unit is not a unit and is not counted, so overhead adds
  spend to a gap and no unit. A restack's or a chat's unit is a unit that spent, and is counted like any. The calibration
  therefore sees a little more gain per unit than the unit steps alone gave; the replay lists the overhead rows of each
  gap so the figure can be judged, which is left to a later change if the amount matters (UNVERIFIED how large it is).
- Metrics: `export_call` attributes are repo, tier, node, role, model and source, never a unit
  (`usage_ledger.py`), and the new node names are a closed set (`track_<phase>` over four phases), so the cardinality stays bounded.

## `abk report`, the usage page and the timeline

- `abk report` groups by unit, change, repository, node, role, model and day from the same entries
  (`usage_report.py:404-430`). Rows with a blank unit are shown in the by-unit view under one `pipeline overhead`
  section with a line per node (`plan`, `track_health`, ...); in the by-node view they are ordinary nodes, and in
  the by-change and by-repository views they sit under the change or repository they carry, else under `(none)`, the
  report's existing label for an absent value. A `restack` row has a unit, so it is on its unit's row and on the
  `restack` row of the by-node view. The sum of every grouping is still the ledger's total.
- The usage page (`serve/metrics.py:344-347`) reads the same records and shows the same `pipeline overhead` line per node.
- Archive: a unit's roll-up keeps its breakdown by node, so its `restack` rows are in its summary. A row with no change
  is not a unit's and is left in the ledger as it is, never rolled up. UNVERIFIED: how the roll-up treats a row whose change is
  blank; the task tests it and the implementation decides, the requirement being that the report's totals do not move.
- Timeline and spans: an overhead call writes no `span` row and no wait, so `abk report --waits` and the node
  duration metric are unchanged. The wait causes sum to a unit's wall time from spans and the unit-graph nodes' agent time;
  an overhead row's `duration_ms` is not added to a unit's agent time, so a `restack` row does not break that sum.
  UNVERIFIED: where a restack's wall time falls among a unit's causes today (it runs in the stack-move handler, often
  while the unit is `in_review` or `planned`); this change leaves it where it is.
- Redaction: a record goes through `append_record`, which withholds secrets from every text field not in
  `IDENTIFYING_FIELDS` (`usage_ledger.py:29-50`). `node` and `unit` are identifying and kept as written. The helper adds no
  text field beyond `outcome`, whose value is `ok` or `failed`, so nothing a prompt or an answer held can reach a row.

## Chat

Chat is recorded. A chat turn spends the account's window as a unit step does, and leaving it out is the gap that
made the analysis wrong. It is one row per turn (each `runtime.run` of the turn builder, `chat.py:443`), node `chat`,
and a turn that resumes a session records its own incremental cost from the ledger baseline. The attach flow's
fix turn (`chat.py:821`) is `chat_commit`. When a session is attached to a unit the row carries that unit, change and repo,
which `leased` already holds; a session with no unit has a blank unit. The row is written on a worker thread: `record_call`
takes the ledger's file lock and never raises, as it does for the unit steps' threads. The transcript the chat keeps is untouched.

## No gateway key for the new sites

A unit step gets a key of its own from the gateway when one is configured, so the gateway's figures can replace the
agent's (`wiring.py:309-331`). That is attributed by the unit's place string and is out of reach of a call with no unit.
The new sites record what the runtime reports (source `reported` or `none`, or `estimated`). A gateway-backed
run's gateway rows therefore stay unattributed for these calls, which is as it is today. Follow-up if wanted.

## The guard test

`tests/test_agent_call_guard.py`, with its scanning in `tests/agent_call_sites.py`, as the timing guard has `tests/timing_hazards.py`.
It parses every module under `src/` with `ast` and finds:

1. each call of `AgentRequest(`, and
2. each call of `.run(` on a runtime: one whose receiver is `runtimes.active()`, `runtimes.get(...)`, `runtime_for(...)`, or a
   name or attribute called `runtime` or `agent`.

A construction passes when it has an `on_result=` keyword, or is the first argument of `recorded(` or a function that calls it.
`on_record=` alone does not pass: it writes transcript events, which is what chat did while writing no row. A `.run(` passes
when its argument is such a request, or when it is in a function that records its result with `call_recorder`. Anything else
is reported with `file:line`, unless `(file, function)` is on the allowlist, which carries a reason per entry. The same
rules as the timing guard apply: the allowlist may only shrink, so an entry whose site now records fails until it is removed,
and an entry whose site is gone fails. Fixture trees with a source file, as in `tests/test_timing_guard.py`, test
the scanner with a call that records, one that records only through `on_record`, an unrecorded one, an allowlisted one, a
stale entry, and a call of `.run(` on something that is not a runtime (`subprocess.run`, `asyncio.run`), which the scanner leaves alone.
The same guard also checks the node name each site passes is a member of the closed `OverheadNode` set, so a typo is a test failure.

Group 1 starts the allowlist with every site not yet converted (planner, tracks, init research, init proposal, the
policy probe, the login refresh, chat, the attach flow), each with the reason "converted by group 2 of this change", so tier 1
stays green between the two groups. Group 2 empties it. A lasting entry would need its own reason, and the design expects none:
the unit steps' `run_agent` passes because its request sets `on_result` when the step has one.

## Node names

`OverheadNode`, a `StrEnum` in `pipeline/vocabulary.py` beside the other closed sets: `restack`, `plan`, `track_health`,
`track_improve`, `track_recommend`, `track_propose`, `init_research`, `init_propose`, `policy_probe`, `login_refresh`,
`chat`, `chat_commit`. The unit graph's nodes stay in `graph/state.py`'s `Node`; the reader's rule above uses a
second constant naming the six that make agent calls. A node name is never reused across the two sets.

## Which group provides what

Group 1 provides the helper, the `restack` node, the reader rule and the guard with its allowlist. Another change records the
conflict resolver's calls from a single session and depends on this change: it needs **group 1 merged**, for the `restack`
node, the helper and the rule that keeps each call of a session as its own row. Group 2 does not feed it.

## Corrections

- The first sketch listed `claude -p` calls only as `AgentRequest` sites. `claude_code.refresh_login` sends a prompt with no request,
  so the guard cannot find it by `AgentRequest(`; it has its own conversion and the guard's second rule is for runtime
  `.run(` calls, not for it. The conversion test names it, and the guard reports any call of `claude` through `subprocess` with
  `-p` in `src/` outside `refresh_login`.
- The policy probe is not recorded by setting `on_result` on its request: it calls `_drive` directly, which never reaches
  `on_result`, so the probe's site records explicitly after `_drive` returns.
- The reader would have merged the new rows into one per node without the rule above.

## Risks

- A row of a new node written on every tick that plans: bounded by the number of plan rounds, one row each.
- Chat rows from a long session: one per turn, each its own record in the report; the report already shows each session's figures per session.
- A runtime that reports no usage gives rows of source `none`; they count as calls and add nothing to a cost total, as for a unit step.
