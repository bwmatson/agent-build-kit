# Tasks

Acceptance: group 5 runs a real build-session chat and a real free session over a scratch installation,
from an uncommitted edit to the reviewed commit, with a stale attachment resolved.

Priority: 4

## 1. [agent-build-kit] [unit-test] The lease carries the attachment, and the tick tells chat changes from leftovers

Needs: resume-over-leftovers group 1 merged — the leftover handling a chat's changes are told apart from
Needs: abk-web-ui group 8 merged — the bridge and the lease this extends (merged)
Needs: abk-web-ui group 9 merged — the unit actions and `requeue` in the CLI module and the server this adds the attach commands and the `attached` cause beside

Done when the lease a chat takes carries what the tick needs, a lease left with uncommitted changes survives its process and
the page, and it can be released.

- [x] 1.1 Test: a turn on the unit's own recorded session can edit files in its worktree and cannot commit or
      push (the tool policy gains a no-commit option beside the existing no-push), for Claude and for ACP,
      and a free session's turn in the same worktree gets none of the builder's policy but still refuses commit and push; the branch
      head is unchanged and the lease is marked as holding changes in the checkout, with the number of changed files.
- [x] 1.2 Test: the lease record, which holds `{holder, pid, started}` today, gains the checkouts, whether they hold changes, the session, the runtime and the branch head, reads as
      before for a lease with no changes (a dead process holds nothing), and reads as a stale lease for one marked as holding changes
      or as a commit made and not delivered; closing the page releases a lease with no changes and keeps one marked as holding changes.
- [x] 1.3 Test: for a dirty worktree, a lease held by a live process leaves the unit alone, a stale lease marked as holding changes
      parks it with the cause `attached` without committing, a killed node's recorded start (the checkpoint's `running_node`, set
      when the node starts and cleared when it completes) with no lease resumes over the leftovers,
      and no lease and no start parks it as unexplained; the status command lists attached units with the number of files.
- [x] 1.4 Test: a unit paused mid-node cannot be attached; one in review, held or failed can; taking the lease over a killed node's
      recorded start adopts the leftovers with the rest and clears the start.
- [x] 1.5 Test: `abk attach release` commits with `--commit`, discards with `--discard`, refuses a dirty tree without either, each as
      one operation; the server takes over stale leases when it starts.
- [x] 1.6 Test: discard lists the files, needs a confirmation, restores the tree and releases the lease in one operation;
      cancelling changes nothing; release with changes present is refused.
- [x] 1.7 Extend the lease record and `Leases._read` (which returns the holder only while the recorded process is alive) with the
      fields and the stale state, keep page close from releasing a lease with changes, add the tick's checks, the turn policy
      keyed on the unit's recorded session instead of the working directory, the no-commit option, discard, `abk attach release`, the `attached` cause and the status line.
- [x] 1.8 Document the lease, the stale state and the tick's decision in `docs/architecture.md` and the pipeline skill, and add a
      changelog entry.

## 2. [agent-build-kit] [unit-test] Commit adopts the changes into the normal cycle

Done when a commit fixes hook failures through the unit's agent, enters at the checks, and its review does
not use a round.

- [x] 2.1 Test: a hook that reformats files is retried and succeeds; a hook the agent must fix gives the
      agent the output, the commit is tried again and succeeds, with progress in the chat; a commit still
      rejected after the bound leaves the changes uncommitted and attached with the output.
- [x] 2.2 Test: one request commits, releases the attachment and delivers the adopted event, with no second request, and answers with
      the commit, the unit's state and that the delivery completed; the event enters
      at the checks from a unit in review, held or failed, clears the recorded node start and carries
      the unit and adopted-from trailers.
- [x] 2.3 Test: a rejected commit answers a conflict with the hook output and keeps the lease and the changes; a commit made and
      not delivered leaves the record marked committed with its hash, and the next server start, `abk attach release` and the tick
      each deliver the adopted event once and remove the record; repeating the request with the same commit delivers nothing again;
      discard and `abk attach release --commit`/`--discard` are each one operation; a planning-checkout commit releases its part.
- [x] 2.4 Test: the previous approval is not reused; the checks use their own fix budget; a failing
      check sends the unit back for rework as usual.
- [x] 2.5 Test: the review after the commit takes no place in the round limit and does not hold a unit
      whose budget was spent; if it asks for changes the following rework is round one; earlier findings
      are kept.
- [x] 2.6 Add `adopted` to `EventKind` and to the event routing, the causes, the round-zero review, the commit through the existing helper bound to the
      attached session, and the single commit-and-release operation with its committed marker and recovery.
- [x] 2.7 Document the flow in `docs/architecture.md` and add a changelog entry.

## 3. [agent-build-kit] [unit-test] The build session knows its change

Done when the unit's own session is given its change and flags a conflict before editing, and a
conflicting review comment is answered in its thread.

- [x] 3.1 Test: a turn on the unit's own recorded session carries the proposal, design, spec deltas and task groups
      read-only and the instruction that tests and code change together, and a free session's turn
      carries neither.
- [x] 3.2 Test: a request that contradicts a requirement gets a flag naming it and no edit; the bridge
      emits the custom event; proceeding makes the change; choosing to change the spec opens a free
      session on the planning repo with the flag as its first message.
- [x] 3.3 Test: the rework prompt tells the agent to answer a conflicting review comment in its thread
      with the flag, and the reply is posted in that thread through the existing replies path.
- [x] 3.4 Add the packaged context and guidance parts, the flag and its event, the callout, and the
      rework prompt line.
- [x] 3.5 Document the rules in `docs/architecture.md` and add a changelog entry.

## 4. [agent-build-kit] [unit-test] Free sessions and commits by another session

Done when a free session can change code and specs together, each checkout is committed with its own
gate, and the unit's agent is told about commits it did not make.

- [x] 4.1 Test: a free session is given no pipeline guidance, may edit a source file and a change's task
      file in one session, and turns run by the server refuse commit and push.
- [x] 4.2 Test: the unit worktree commit goes through the commit helper and is adopted; the planning
      checkout commit is gated by `abk check` and `abk tags`, failures are given to the agent and the
      commit tried again, and nothing is delivered to a unit.
- [x] 4.3 Test: the consequences list names a `Needs:`-only edit, a plan change with built units and a
      requirement a started unit built to, and changes none of them.
- [x] 4.4 Test: a commit by a free session carries the adopted-from trailer, and the next rework,
      check-fix and review prompts list it (hash, subject, files, session) as authoritative; a commit
      by the unit's own session and a review comment add nothing; an outside commit that changed a test
      is accounted for only if the agent changes the test.
- [x] 4.5 Add the per-checkout commit, the planning gate and loop, the consequences list, the trailer and
      the outside-commit prompt part.
- [x] 4.6 Document free sessions in `docs/architecture.md` and add a changelog entry.

## 5. [agent-build-kit] [e2e-test] [acceptance] Editing from chat over a real scratch installation, on Claude Code


Needs: tier2-tests-are-tagged-by-runtime group 18 — parked until the live tests are tagged by runtime and the drift test guards them, so an ACP test that cannot run (the model backend is out of budget) is held instead of failing
Split: claude_code


Done when a real run goes from an uncommitted chat edit to a reviewed commit, with a free session and a
stale attachment handled, on Claude Code; the same flows on ACP are group 6, which waits for the ACP split to be
released.

- [x] 5.1 Test (`local_stack`, tagged `runtime_claude_code` through `CLAUDE_CODE_PARAMS`, as
      `tests/integration/test_graph_unit.py` does; the module carries no `runtime_acp` mark and never
      `RUNTIME_PARAMS`, since a test may carry one runtime tag): over a scratch installation with a real agent, a build-session chat edits a
      test and its code without committing, a hook failure is fixed by the agent, the commit is adopted,
      the review does not use a round and no outside-commit part is added; a free session changes code and
      a change's task file together, both are committed, and the next rework lists the outside commit; a
      request against a requirement is flagged; a stale attachment is released from the command line.
- [x] 5.2 Write the acceptance run and document how to run it.
- [x] 5.3 The scratch installation is built by the fixture for the runtime under test, held in one place so
      group 6 reuses it: a `scratch` fixture takes the runtime from its parameter and calls
      `runtime_scratch(runtime, ...)`, and the `"runtime"` field of the free-session request body (the
      `/api/sessions` call that starts it) is that parameter, not the literal `"acp"`. For Claude Code the
      recorder is a wrapper script set as `runtimes.claude_code.command` in the scratch `abk.yaml`: it copies its
      standard input to the prompts file and then `exec`s `claude "$@"`, so it records the prompt of a `-p` run
      and of a `--resume <id>` run and leaves no process of its own (the process arguments are Claude's, with the
      session id, so `claude_holders` in `serve/chat.py` is not confused by it). The assertions that read what
      the agent was told (`prompts_told`: the outside-commit part, the round-zero review) read that file, and
      the module keeps the helpers (`converse`, `said`, `head`, `changed`, the fixtures) importable by group 6.
      Rename `tests/integration/test_chat_editing_acp.py` to `test_chat_editing_claude_code.py` and drop its
      `REASON` constant, which says the scenarios run on ACP alone.

## 6. [agent-build-kit] [e2e-test] [acceptance] Editing from chat over a real scratch installation, on ACP


Needs: ui-chat-editing group 5 — the scratch fixture, the helpers and the scenarios this group runs again on the other runtime live in group 5's module
Split: acp

Done when the flows of group 5 are proven on the ACP runtime, in the ACP split, which stays held until the
backend has budget; nothing in the Claude Code group changes.

- [ ] 6.1 Test (`local_stack`, tagged `runtime_acp` through `RUNTIME_PARAMS`' ACP parameter, the module with no
      Claude Code mark): `tests/integration/test_chat_editing_acp.py` imports group 5's fixture and helpers and
      runs its scenarios (flag, edit-hook-commit-review, free session over two checkouts, outside commit listed,
      stale attachment released from the command line) with the runtime parameter `"acp"`: the scratch installation
      is `runtime_scratch("acp", ...)`, the `"runtime"` field of the request body is `"acp"`, and the recorder is
      the line-forwarding script that wraps `runtimes.acp.command` and appends each line the client sends, as
      the module did before group 5 made it the Claude group. It fails, not skips, when
      `<redacted>` names no agent.
- [ ] 6.2 Document in `docs/agent-runtimes.md` that this module is in the `acp` split, held, and that the
      scenarios are shared with the Claude Code module; add a changelog entry.
