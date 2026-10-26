# Design

## Why

`fix_checks` starts a brand-new agent session. The agent that wrote the code is
replaced by one that has to rediscover it, and the prompt it gets
(`CHECKS_PROMPT`, `pipeline/wiring.py`) carries only the change path, the task
group numbers, the stored tier-1 failure output and the boundary notes. It does
not have the task text, the implement conversation, or what earlier fix rounds
tried. Every fix round therefore pays to re-read the worktree and re-derive
intent that the build session already held.

Resuming the build session for the fix removes that cost: the agent already
knows the change, and the prompt shrinks to what is new. The same mechanism is
useful beyond this loop (feedback from review can go back to the author), so the
design is to make *every* agent node record its session, and make *which roles*
resume their previous session a per-role switch in configuration, on by default
for the build role.

## Where things stand

The pieces exist but are connected only for crash recovery.

- `UnitRun.session_id` (`graph/state.py`) holds the session of the node that is
  running. `_record_sessions` (`graph/unit.py`) writes it into the thread as
  soon as the runtime reports it, and the node wrapper clears it when the node
  completes (`graph/nodes.py`, `return {**update, "session_id": ""}`). So the id
  exists only while its node runs, and nothing links `fix_checks` to the
  `implement` session.
- `_run_agent` (`graph/nodes.py`) resumes `state.session_id` if set and falls
  back to a new session on `SessionUnavailable`. That is crash-resume of the
  *same* node.
- `run_claude` (`pipeline/wiring.py`; renamed `run`, see "Rename" below) swaps the prompt for `INTERRUPTED_PROMPT`
  whenever `resume_session` is set ("the process was interrupted, re-read the
  worktree, finish the task"). Resume and "send this new prompt" are conflated:
  there is no way to continue a session with a different message.
- `AgentRuntime` (`runtimes/base.py`) has `supports_session_resume`,
  `AgentRequest.resume_session` and `SessionUnavailable`. The Claude Code
  adapter supports resume (`--resume <id>`); the ACP adapter does not
  (`supports_session_resume = False`, a fresh connection and `new_session` per
  call, `session/load` unused).
- The usage ledger (`pipeline/usage_ledger.py`) already records
  `(unit, node, round, session_id, resumed)` durably, and folds a resumed call
  into the call it resumed. It is a record of spend, not a source of truth for
  routing.

## Design

### Sessions are recorded by role, in graph state

A session is recorded under a **role**, not under the node that ran it. A role
is "one conversation with one context"; several nodes can speak in the same
one.

```python
class SessionRole(StrEnum):
    BUILD = "build"  # tests, implement, fix_checks, rework, adapt: edits the code
    REVIEW = "review"  # review, rework_review: judges it
    # one further member per other agent node that keeps its own conversation
```

A single table maps each agent node to its role. The agent nodes are the six in
`AGENT_NODES`, and two roles cover them:

| Node | Role |
|---|---|
| `tests`, `implement`, `fix_checks`, `rework`, `adapt` | `build` |
| `review` | `review` |

(`review` also runs the follow-up rework-review prompt inside the same node, so it
stays in the one session.)

A role is a conversation, not a stage of the flow: it names which nodes share one
agent context. A node gets its own role only when it should *not* share context
with the others, as `review` must not. `adapt` is part of the build flow and
shares its context, so it is in `build`. Moving a node between roles,
or giving a node its own, is a one-line change to that table.

State gains a record per role, held separately so roles never overwrite each
other:

```python
class AgentSession(Frozen):
    session_id: str
    runtime: str  # which runtime owns the id; ids are not portable
    model: str  # the model the session started with
    node: Node  # the node that last spoke in it
    round: int
    head: str  # worktree head when the node completed


class UnitRun(Frozen):
    ...
    session_id: str = ""  # unchanged: crash-resume of the running node
    sessions: Mapping[SessionRole, AgentSession] = {}
```

Every agent node writes its role's entry when it completes, whether or not reuse
is on for its role. That is what makes restoring work something any node can do
later without touching the graph: the data is always there.

`session_id` keeps its current meaning (the running node, cleared on
completion) and keeps priority: a node that was killed mid-run resumes *its own*
session before the reuse flag is consulted.

`AgentSession` and the mapping must be added to `ALLOWED_MSGPACK_MODULES` in
`graph/checkpointer.py`, and a checkpoint written before this change (no
`sessions`) must load with the default empty mapping.

### Review is always its own session

The `review` role never resumes a previous review session (a reviewer anchored
on its own earlier verdict is a worse judge) and never resumes the `build`
session (a judge sharing the author's context is not independent). Its id is
still recorded, for crash-resume, audit, and so the flag could change later.

What does flow between them is *feedback*: the findings of a review are
delivered **into** the `build` session, as a continuation prompt, so the author
fixes them with full context. The review session stays untouched.

### Reuse is a per-role flag

Reuse is a boolean per role in `abk.yaml`. When a role's flag is true, every
node in that role is handed the role's previous session id and continues it;
when false, each node starts its own session, as today:

```yaml
session_reuse:
  build: true       # the default
  review: false     # fixed: see "Review is always its own session"
```

A role not listed is false. Turning reuse on for another role later is one line,
with no graph change; turning the feature off is `build: false`.

The field lives in `config.py` (pydantic, `extra=forbid`, default set), and is
documented in `docs/configuration.md` and the `abk-config` skill. Validation
rejects `review: true`, so judge independence is enforced and not a convention.

Because the flag is per role, not per node, there is no table of which node
continues which. Every node of a reusing role continues the role's latest
session, whichever node wrote it. That has a consequence worth stating: with
`build: true`, `implement` continues the session `tests` ran in, `fix_checks`
continues `implement`'s, and a later `rework` continues whichever build node
spoke last. If `tests` and `implement` should *not* share a conversation, that is
a reason to give `tests` its own role in the node-to-role table, not a second
setting.

### Resolution: one step decides session and prompt together

Before an agent node calls its runtime, one resolution step, in `_run_agent`,
chooses a session and a prompt mode, and for a resumed session adds the
staleness preamble (see "Staleness"):

1. `state.session_id` set (this node was interrupted): resume it with the
   existing crash-resume behaviour. Unchanged.
2. Else, reuse is on for this node's role and `state.sessions` has an entry for
   that role that is usable (below): resume it with the node's **continuation
   prompt**, using the **model stored in that entry**.
3. Else, start a new session with the node's **full prompt** and its configured
   model.

If the resume of case 2 raises `SessionUnavailable` (the id is gone, the runtime
cannot resume, the context overflowed), the step falls through to case 3 *in the
same call*: new session, full prompt, and the node's model (the configured one, or `build_model` for `fix_checks`). The prompt mode is
chosen by the same step that chooses the session, so a fallback can never leave
a cold agent holding a stub that assumes context it does not have. The ledger
and log record `resumed=False` and why.

An entry is **usable** when it comes from the same runtime that will run the
node (ids are not portable between runtimes) and the runtime reports
`supports_session_resume`. Whether the worktree moved under the session is
covered in "Staleness".

### Two prompts per reuse-capable node

A node that can be resumed has two prompts:

- the **full** prompt: today's, self-contained, used for a cold start or a
  fallback;
- the **continuation** prompt: only what is new, used when the session is
  resumed, and it does not re-pass the initial context.

For `fix_checks` the continuation prompt is the failure output (or a pointer to
it, since the output may be cut short) and the instruction to run the checks
itself, fix, and run them again. It drops the change path, the task group
numbers and the boundary notes, which the build session already holds; those
fields move to the full-only prompt. The design pass lists, field by field, which
of `CHECKS_PROMPT`'s inputs are in each.

Because the agent may have compacted its context (below), the continuation
prompt still says to re-run the checks and re-read what the failure names, and
does not assume the earlier conversation is verbatim.

`run` needs a way to resume with a real prompt. Today resume forces
`INTERRUPTED_PROMPT`; the request gains an explicit follow-up prompt, and the
two intents are separate:

| Intent | Session | Prompt |
|---|---|---|
| crash-resume | the node's own `state.session_id` | `INTERRUPTED_PROMPT` (unchanged) |
| continuation | another node's role session | the node's continuation prompt |

### One entry point: `run_claude` becomes `run`, and `run_rework` goes

`run_claude` is the entry point every agent node uses, and it already dispatches
to whichever runtime is configured (Claude Code or ACP). The name is stale: the
session reuse described here is a feature of both runtimes, and the function
should not read as Claude-specific while it grows resume and follow-up
parameters. It is renamed `run`.

`run_rework` is the same function built a second time with a different baked-in
model and a log label (`pipeline/wiring.py`), so a node picks its model by
picking a runner. Choosing the model per call is now the resolution step's job (a
resumed session's recorded model, `build_model` for `fix_checks`, else the node's
configured model), and a baked-in model cannot do that. So there is one `run`,
and it takes the model per call; `run_rework` is removed, its callers (`rework`,
`adapt`, `fix_checks`) call `run`, and the node-to-model choice moves into the
resolution step. The `role="rework"` label on the old runner is dropped: the node
name already identifies the call, and it is not the session role of this design.
`run_review` stays separate; it builds a different prompt.

The rename and the merge are mechanical but wide (about a hundred references,
mostly in tests and a few in `planner.py`, `cli/init.py` and
`docs/agent-runtimes.md`), so they land as their own first task, with no
behaviour change, before the session work builds on them. Anything genuinely
Claude Code-specific (the `claude_code` adapter, `--resume`) keeps its name.

### `tests` starts the build session

`tests` is the first agent node of a unit's build path (`prepare -> tests ->
implement`), so in the normal case it is the node that creates the `build`
session; `implement`, `fix_checks`, `rework` and `adapt` then continue it. There
is one conversation from the tests through the implementation to the fixes, so
`implement` already holds the tests it has to make pass and why they are shaped
as they are.

What changes for `implement`:

- Its continuation prompt carries only what `tests` did not already have: the
  instruction to implement, and the changelog note, which only `implement`'s
  prompt carries. It drops the change path, the task group numbers and the
  boundary notes, which the session already holds. The follow-ups note, which
  both prompts prepend, goes in the full prompt only (it is part of the context
  the first node received), unless the follow-ups changed between the two.
- `tests` and `implement` use the same model, so a resume needs no model switch.
- `tests` is a cold start by construction, so it always gets the full prompt and
  its session is the first `build` entry. A unit that enters past `tests` (a
  restack, feedback, a resumed unit) has no `build` entry and starts cold at
  whichever node comes first, which then starts the session.

The session carries the test-writing conversation into `implement`. That is
accepted: it is what the unit's author knows.

### `adapt` continues the build session

`adapt` ports a unit onto a predecessor it could not be replayed onto: the branch
is reset to the new base, the old work kept under a ref, and the agent ports it.
Today it starts cold on the rework model, with the change path, task groups, the
old base and the old test list in its prompt. The agent that wrote the work is
the one that knows why it is the way it is, so `adapt` is in the `build` role and
continues that session when `build` reuse is on.

What changes for `adapt`:

- The staleness preamble covers the move. The agent is told its old head and the
  new one, which replaces passing `old_base` and the commit detail; it does not
  need the commits relayed. The branch *was* reset, so the old head is no longer
  on the branch, but `adapt` keeps it under `refs/spec-driven/pre-adapt/<unit>`,
  so it stays reachable and the "old head unreachable" fallback does not fire.
  After a reset the new head is not a descendant of the old one, so the preamble's
  `git range-diff` form is the one that applies; the ref is also named in the
  continuation prompt.
- The continuation prompt keeps what is new: the predecessor's identity and
  intent, the conflict text, the ref holding the old work, and the instruction
  to decide, for each old test that did not carry over unchanged, whether it still
  belongs, in the answer format the pipeline parses (that format is the node's
  contract, so it stays in the prompt, resumed or not). It drops the change path
  and task groups.
- Its model is the session's recorded model, as for any resumed build node.
- A killed `adapt` that already reset the branch resumes its own session first
  (crash-resume), as today.
- The test decisions still go to the `review` role, which is a separate session
  and so judges them independently of the author who made them.

### Model: `fix_checks` runs on `implement`'s model

`fix_checks` has no model of its own. It always runs on the model the unit's build
session started on (the implement model, since `tests` and `implement` both use
it), whether or not session reuse is on: the agent fixing the checks is
the one that wrote the code, and a different model should not take over for the
fix. The `models.rework` setting no longer applies to `fix_checks`; it applies to
`rework` only.

The model is recorded, not re-read from config, so a config change between nodes
cannot split a unit across models. `UnitRun` gains `build_model`, the model the
unit's build session started on: written by whichever of `tests` and `implement`
runs first (both use the implement model, and `tests` normally runs first), and
never overwritten by a later node. When it is
empty (a unit that entered the graph past the build nodes, or a checkpoint from
before this change), `fix_checks` falls back to the configured implement model.

How this meets reuse:

- **Reuse on.** The resumed session is `implement`'s own thread, so its model and
  `build_model` agree and the call pins that model. Each runtime must let a
  resume call pin the model: Claude Code accepts `--model` alongside `--resume`;
  for ACP the model is session configuration, which a loaded session already
  carries (to verify). If the stored session's model ever differs from
  `build_model` (an upgrade, or a model changed mid-unit) and
  the runtime cannot switch models on resume, the step falls back to a cold start
  with the full prompt, on `build_model`.
- **Reuse off, or a fallback.** A new session with the full prompt, still on
  `build_model`.

Other nodes keep their configured models on a cold start. A resumed node of
another reusing role runs on its session's recorded model, as `AgentSession.model`
says. The effective model is what the ledger records.

### Staleness: say what moved, let the agent read it

A session is a record of what the agent saw, and the worktree can change under
it: a rebase onto a moved base, a human commit, a different `head`. The design
does not try to classify those changes or discard the session over them. The
entry stores the `head` at completion, and **the resolution step owns the
staleness preamble**: when it resumes a session it compares that head with the
worktree head and, if they differ, prepends a preamble to the node's
continuation prompt. The nodes do not each handle it, so every reusing node gets
it identically, and a node's own continuation prompt stays about its task. The
preamble says what moved in git terms and leaves the reading to the agent:

> The branch moved since your last turn: `<old>` to `<new>`. Read what changed
> (`git log <old>..<new>`, or `git range-diff` if the history was rewritten),
> then continue.

When `<old>` is an ancestor of `<new>` the range is the commits that landed,
including the node's own, which the agent will recognise. After a rebase the
old head is no longer an ancestor, and the prompt names both hashes so the agent
can compare them. When the heads are equal, nothing is added. The prompt carries
the two hashes only, never the log or diff, so its size does not grow with the
change.

A session is dropped for a cold start with the full prompt only when it cannot
be used at all: the old head is unreachable (garbage-collected after a rewrite,
so the agent could not read it), or the runtime reports `SessionUnavailable`.
A review-round boundary does not invalidate the build session: feeding review
findings back to its author is the point.

### Context growth: let the agent compact

There is no reuse-depth cap and no token threshold that forces a fresh start.
The design relies on the agent's own auto-compaction as the session grows across
fix rounds, and verifies per runtime that it happens in a resumed headless
session (Claude Code does; <redacted> auto-compresses context, see Runtime support). One
escape hatch stays: a resumed call that fails with a context-overflow error is
treated as `SessionUnavailable` and falls back to a fresh session with the full
prompt.

Compaction can drop detail. That is accepted, and is why the continuation prompt
points the agent at the checks and the worktree rather than at its memory.

## Runtime support

- **Claude Code.** `--resume <id>` is implemented, and the id arrives through
  the stream-json init event. This is the path the first version ships on. The
  adapter needs the follow-up prompt and model pin described above.
- **ACP.** `supports_session_resume = False` today: each call is a fresh
  connection and a `new_session`, and neither `session/load` nor `session/resume`
  is used (the only capability read is additional directories). The protocol has
  both, and the pinned SDK (`agent-client-protocol` 0.12.1) exposes both on the
  client connection. `session/load` replays the whole conversation to the client
  as `session/update` notifications; `session/resume` restores the context
  without replay. An agent advertises them at `initialize` (`loadSession`, and
  `sessionCapabilities.resume`). The adapter reads those, sets
  `supports_session_resume` from `resume` and `list` together, and on a resume
  calls `session/resume` with the stored id instead of `new_session` (after the
  existence check below). An agent that does not advertise both falls back to a
  cold start, so reuse degrades to today's behaviour and
  is never an error.

  **<redacted>, checked against its local ACP adapter (`acp_adapter/server.py`,
  `session.py`):**
  - It advertises `load_session=True` and `session_capabilities` with `resume`,
    `fork` and `list`.
  - Sessions are persisted to its session database and restored on demand, so an
    id survives the process exit that ends every call here (abk spawns a new
    agent process per call). Its stdio shutdown stamps the session ended, and a
    load or resume reopens it.
  - The restored session keeps the model it started with (stored with the
    session), and `set_session_model` exists for switching it when idle. That
    matches the model rule above without a separate pin.
  - It auto-compresses context (`agent/context_compressor.py`), so the
    auto-compaction assumption holds for <redacted>.
  - **Trap:** `resume_session` on an unknown id does not fail. It logs, creates a
    *new* session and answers normally, and the response carries no session id,
    so the client cannot tell. A stale or purged id would therefore turn a
    "resume" into a cold start that is sent the short continuation prompt.
  - **Decision: `session/resume`, guarded by `session/list`.** The adapter does
    not use `session/load` (it replays the whole conversation to the client, which
    the runtime would have to recognise and discard). Before resuming, it checks
    that the id exists, and when it does not, it cold-starts with the full prompt,
    as for `SessionUnavailable`. The check, as <redacted> implements `list`:
    - pass the worktree as `cwd`, so the listing is the unit's own sessions, and
      follow `next_cursor` until the id is found or the pages end (results are
      paged and newest first, so a recent build session is on the first page);
    - <redacted> lists only sessions that have messages and are within its most
      recent thousand, so absence means "cannot be resumed", the case that
      matters, and presence is the case where `resume` will find it;
    - the stored cwd moves to the worktree on each resume, so the unit's worktree
      path must stay stable across the build loop (it does); if it moved, the
      filtered listing would miss a live session, which is a cold start and not
      an error.
    The check and the resume are two calls, so a session purged between them
    still falls through to the silent new session. That window is small, and it is
    accepted: the result is one fix round that starts cold on the short prompt
    and tells the agent to re-run the checks and read the worktree.
    An agent that advertises `resume` but not `list` is not resumed.

  Other ACP agents are only as good as what they advertise; the capability check
  is what keeps them safe.
- **Retention.** `docs/agent-runtimes.md` already lists as open what a run's
  sessions cost an agent that keeps them, and whether ACP exposes cleanup.
  Reuse makes sessions live longer, so this question gets more weight. It is
  noted there, not solved here.

## Making reuse a config change

With the sessions always recorded and the flag per role, turning reuse on for a
role is a config line, and moving a node into or out of a reusing role is a line
in the node-to-role table. What must be true of every node in a role before its
flag is turned on, to be checked each time and stated in the docs:

- each node has a continuation prompt (or its full prompt is acceptable to send
  into a warm session);
- the role's session is one it makes sense to continue (never `review`);
- the stored model suits every node that will run on it.

## Durability and failure modes

- **Crash mid-node.** `state.session_id` takes priority, as today.
- **Session gone or runtime changed.** `SessionUnavailable`: fall through to a
  fresh session with the full prompt.
- **In-flight units at upgrade.** A checkpoint without `sessions` loads with it
  empty, so the first resolution after the upgrade is a cold start and nothing
  breaks.
- **Idempotent re-runs.** A node re-run after a checkpoint replay reads the same
  `sessions` entry it read the first time; an entry is only replaced by a node
  completing, never by a resolution.

## Observability

The ledger already carries `session_id` and `resumed`. Add the effective model
and the role. The node span gains `session.reused`, `session.role` and
`session.source_node`, and the node's log line states which session it
continued, or why it did not. Usage is attributed to the node that made the call:
a `fix_checks` call that resumes an `implement` session is `fix_checks` spend.
Today the usage reader folds a resumed call into the call it resumed, which was
right for crash-resume within a node and is wrong across nodes. It changes to key
on `(unit, node, round)` and carry the session id as an attribute, so one session
id appears under several nodes, and the fold applies only to a same-node
crash-resume.

## Testing

- The resolution step, table-driven: interrupted node; reuse on; reuse on with a
  moved head (ancestor, rewritten, unreachable); reuse on with an unsupported runtime; `SessionUnavailable`
  fallback re-sending the full prompt and the node's model; reuse off; `fix_checks` on `build_model` with reuse on and off, and with `build_model` empty.
- A graph test with a fake runtime: `fix_checks` receives the id and model of
  the `implement` session and the continuation prompt; `review` never does.
- Checkpoint round-trip of the new state types, and loading a checkpoint that
  has no `sessions`.
- Config: the defaults, and the rejection of `review: true`.
- The ACP adapter: capability negotiation, with an agent that advertises
  loading and one that does not.

## Rollout

- Behind the per-role flag, so shipping with `build: true` is the feature and
  `build: false` is the off switch.
- A `CHANGELOG.md` bullet under `## Unreleased`; updates to `docs/unit-graph.md`
  ("Session capture and resume") and `docs/agent-runtimes.md` once built.
- No installation or consumer names in any of it
  (`tests/test_no_installation_leaks.py`).

## Settled

- **Name.** `run_claude` becomes `run`.
- **Roles.** Two cover all six agent nodes: `build` and `review` (table above).
  A further role is added only for a node that must not share context.
- **Review feedback into the build session.** No new node: `review -> rework`,
  and `rework` is in `build`, so it continues the build session. Its
  continuation prompt carries the review or PR-comment feedback.
- **Usage attribution.** A resumed call's spend is counted under the node that
  made it (`fix_checks` for a fix), not the node whose session it continued. A
  session id can appear under many usage buckets; the usage reader keys on
  `(unit, node, round)` and treats the session id as an attribute, not a key.
- **One runner.** One `run` taking the model per call; `run_rework` is removed
  (above).
