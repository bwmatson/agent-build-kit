# Tasks

Acceptance: none — the graph's choice of session, prompt and model, and the ACP adapter's
capability and listing checks, are proved at tier 1 with fake runtimes and a fake ACP
agent; a run against a real <redacted> is a follow-up, not a gate.

## 1. [agent-build-kit] [tier1] One `run` entry point, taking the model per call

Done when every agent node calls `run`, `run_rework` and `run_claude` are gone, and no
behaviour changed.

- [x] 1.1 Test: `rework`, `adapt` and `fix_checks` call `run` with the rework model, and
      `tests` and `implement` call it with the implement model, and the prompts and
      working directories are the ones they pass today.
- [x] 1.2 Test: the commit step's "send a rejected commit back" call goes through `run`.
- [x] 1.3 Replace `build_run_claude` and the `run_claude`/`run_rework` pair with one `run`
      taking `model`; move the choice of model into the nodes; drop the `role="rework"`
      label; keep `run_review`.
- [x] 1.4 Rename in the tests and in `docs/agent-runtimes.md`; add a changelog entry.

## 2. [agent-build-kit] [tier1] Record each node's session under its role

Done when a completed agent node leaves its role's session in the unit's state.

- [x] 2.1 Test: after `implement` then `review`, the state holds a `build` and a `review`
      session; a later `fix_checks` updates `build` and leaves `review` unchanged.
- [x] 2.2 Test: a unit state from before this change loads with no sessions; the new types
      survive a checkpoint round trip.
- [x] 2.3 Test: `build_model` is written by the first build node to run and not changed by
      a later one.
- [x] 2.4 Add `SessionRole`, the node-to-role table, `AgentSession`, `UnitRun.sessions` and
      `build_model`; write them when a node completes; allow the types in the checkpointer.

## 3. [agent-build-kit] [tier1] The per-role reuse setting

Done when `session_reuse` is read from `abk.yaml` with the right defaults and rejections.

- [x] 3.1 Test: the defaults are `build` on and `review` off; an unnamed role is off.
- [x] 3.2 Test: `review: true` is rejected naming the setting; an unknown role is rejected.
- [x] 3.3 Add the field to `config.py` with its default and validation; document it in
      `docs/configuration.md` and the `abk-config` skill.

## 4. [agent-build-kit] [tier1] Continue a session with a new prompt, on the right model

Done when a node continues its role's session with its continuation prompt, and falls back
to a new session with the full prompt.

- [x] 4.1 Test: `fix_checks` with reuse on and a recorded build session resumes it with a
      prompt that has the failure output and not the change path or task groups, on the
      recorded model.
- [x] 4.2 Test: with reuse off, `fix_checks` starts a new session with the full prompt on
      `build_model`, not the rework model; with `build_model` empty it uses the configured
      implement model.
- [x] 4.3 Test: `SessionUnavailable`, a context overflow, a runtime that cannot resume and
      an unreachable recorded head each start a new session with the full prompt and record
      why; an interrupted node still resumes its own session with the interruption prompt.
- [x] 4.4 Test: `review` never resumes, in a second round or from a build session.
- [x] 4.5 Test: a moved head puts the two hashes at the start of the prompt with no log or
      diff; equal heads add nothing; after `adapt`'s reset the note names the ref holding
      the old work.
- [x] 4.6 Test: `implement` continues the session `tests` started; `adapt` and `rework`
      continue the build session, and a unit entering at `adapt` starts it.
- [x] 4.7 Add the follow-up prompt to the agent request and `run`; add the resolution step
      to `_run_agent`; add continuation prompts for `implement`, `fix_checks`, `rework` and
      `adapt`, keeping `adapt`'s test-decision format; keep `review` out of reuse.
- [x] 4.8 Update `docs/unit-graph.md` ("Session capture and resume") and add a changelog
      entry.

## 5. [agent-build-kit] [tier1] Resume ACP sessions, guarded by a listing

Done when an ACP node resumes a listed session and starts a new one otherwise.

- [x] 5.1 Test: with a fake ACP agent advertising both capabilities, a listed id is resumed
      with `session/resume` and no new session is opened; an unlisted id opens a new
      session and the node gets the full prompt.
- [x] 5.2 Test: an id on a later page is found by following the cursor; an agent advertising
      only one of the two capabilities gets a new session and no error; `session/load` is
      never called.
- [x] 5.3 Read the capabilities at initialize, set `supports_session_resume` from them, add
      the listing check and `session/resume` to the ACP runtime; note the <redacted> behaviour
      and the retention question in `docs/agent-runtimes.md`.

## 6. [agent-build-kit] [tier1] Attribute usage to the node that made the call

Done when a resumed call is counted under its own node.

- [x] 6.1 Test: `implement` then `fix_checks` in one session give each node its own spend,
      both records carrying the session id; a node killed and re-run counts once.
- [x] 6.2 Key the ledger reader on unit, node and round, with the session id as an attribute,
      folding only a same-node crash-resume; update the docs that describe the ledger
      (`docs/unit-graph.md`, `docs/architecture.md`) and add a changelog entry.
