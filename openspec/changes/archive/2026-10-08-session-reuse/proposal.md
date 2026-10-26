# Proposal

## Why

`fix_checks` starts a new agent session. The agent that wrote the code is replaced by one
that is told only the change path, the task groups, the failing output and the boundary
notes. It has not seen the task text, the implementation, or what earlier fix rounds tried,
so every round pays to re-read the worktree and re-derive intent the build session already
held. `rework` and `adapt` do the same: each starts cold on work an earlier node in the same
unit wrote.

The pieces to avoid this exist but only serve crash recovery. The session id is held in
state only while its node runs and is cleared when the node completes, so nothing links a
later node to an earlier node's session. Resume also forces the "you were interrupted"
prompt, so a session cannot be continued with a different message, and the ACP runtime
never resumes: each call is a new connection and a new session, although <redacted>, the ACP
agent in use, advertises `session/load` and `session/resume` and keeps sessions across
processes.

## What Changes

- **Sessions are recorded by role, in graph state.** A node completing writes its role's
  entry (session id, runtime, model, round, head). Two roles cover the six agent nodes:
  `build` (tests, implement, fix_checks, rework, adapt) and `review` (review, including its
  rework-review prompt). `tests` normally starts the build session; the others continue it.
- **Reuse is a per-role flag in `abk.yaml`** (`session_reuse: {build: true, review: false}`).
  When on, every node of the role is handed the role's latest session; when off, behaviour
  is today's. `review: true` is rejected: the judge is never the author's session, and
  never its own earlier one.
- **One step picks the session, the prompt and the model.** It resumes an interrupted node's
  own session first, else the role's session when reuse is on and the session is usable,
  else starts new. A resumed node gets its **continuation prompt** (only what is new); a new
  session gets the **full prompt**, including after a fallback. A moved branch head is
  reported to the agent as two hashes, and it reads the change itself.
- **`fix_checks` runs on the model the build session started on**, with or without reuse.
  A resumed session keeps the model it started with.
- **ACP resumes.** The adapter reads the agent's advertised capabilities, resumes with
  `session/resume` only after `session/list` shows the id, and otherwise starts a new
  session.
- **One `run` entry point** replaces `run_claude` and `run_rework`; it takes the model per
  call.
- **Usage is attributed to the node that made the call.** A session id may appear under
  several nodes.
- Context growth is left to the agent's own compaction; a resumed call that overflows falls
  back to a new session with the full prompt.
