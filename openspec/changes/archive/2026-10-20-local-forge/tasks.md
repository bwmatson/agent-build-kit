# Tasks

Acceptance: group 3 runs a unit through a repo with no remote — built, reviewed in the UI, sent back,
approved, merged by a person with git — and the pipeline moves on.

Priority: 4

## 1. [agent-build-kit] [unit-test] The local forge

Needs: ui-review group 3 merged — the review store the forge reads and the UI comment source

Done when a `local` forge opens, finds, updates, lists and closes pull requests and reads and writes
review notes from the state directory.

- [x] 1.1 Test: with `forge: local`, creating then finding a pull request records and returns it
      with a number, head and base, with no network call, and updating or closing it is recorded.
- [x] 1.2 Test: listing returns conversation ids, comment bodies and the review decision from the
      review store, and the poller's tests for host forges pass against it unchanged.
- [x] 1.3 Test: label, draft, status, check and stack operations are accepted and change nothing, and every
      Protocol attribute and method has an entry in `OPERATIONS` and an implementation on the local forge.
- [x] 1.4 Test: the forge is registered behind `ResilientForge`, a repo selects it by setting, and it is not
      inferred from a remote.
- [x] 1.5 Write the forge over `ReviewStore` and the UI-review source, add its `OPERATIONS` entries, register it; document the setting in `docs/code-forges.md`.

## 2. [agent-build-kit] [unit-test] Merge detection, no remote and the read commands

Done when a person's git merge is seen, a repo with no remote builds against its own trunk, and an
agent can read its local pull request.

- [x] 2.1 Test: a pull request is merged when its tip is in the trunk or its patch identity is, for a
      merge commit, a fast-forward and a squash, and open when neither.
- [x] 2.2 Test: for a repo with no `origin` the push, fetch and base comparison (`push_target`, the per-unit
      and per-pass fetch, `local_ref` and the dev-stack base) use the local trunk and
      local branches, and the push gate still requires the approved commit; with a remote, behaviour
      is unchanged.
- [x] 2.3 Test: `abk pr view` and `abk pr diff` print the local pull request and its diff and change
      nothing, and appear in the forge's read commands and not its denied ones.
- [x] 2.4 Add the merge check, the local-aware push and base handling and the two commands.
- [x] 2.5 Update `docs/code-forges.md` and `docs/architecture.md`, and add a changelog entry.

## 3. [agent-build-kit] [e2e-test] [acceptance] A unit reviewed and merged without a code host


Needs: tier2-tests-are-tagged-by-runtime group 18 — parked until the live tests are tagged by runtime and the drift test guards them, so an ACP test that cannot run (the model backend is out of budget) is held instead of failing
Split: claude_code

Done when a real unit is built, reviewed in the UI, reworked, approved and merged by a person with
no remote pull request. The acceptance runs on Claude Code only: the acp split is held (its model backend is
out of budget), so a `runtime_acp` test here would park and run nothing. Estimate: about 40 changed lines.

- [x] 3.1 Test (`local_stack`): over a scratch installation whose repo has no remote and a real agent,
      a unit reaches review, a UI comment sends it back and it is reworked, Approve is recorded, a
      person merges with git, and the unit is recorded merged and its dependent starts. The scratch
      change's second group names the first group's function in its own test (so any plan makes it
      a separate unit that depends on the first), and the test asserts the plan's shape after the
      first tick with a message that blames the planner, not the merge. The UI comment and the
      approval go through the real endpoints, not copies of their handler code.
- [x] 3.2 Write the acceptance run and document how to run it.
- [x] 3.3 Make 3.1 Claude-only in `tests/integration/test_local_forge_unit.py`: the `scratch` fixture builds its
      runtime with `runtime_scratch("claude_code", ...)` (it was `"acp"`); the module's `runtime_acp` mark becomes
      `runtime_claude_code` (one runtime tag only, never `RUNTIME_PARAMS`; where a fixture is parametrized use
      `CLAUDE_CODE_PARAMS`, as `tests/integration/test_graph_unit.py` does); the call to `assert_unit_session_listed`
      and its `monkeypatch.setenv` loop are removed, because it lists sessions with ACP `session/list`, which a
      Claude Code agent does not offer (the assertions on the unit's state, branch and plan shape stay); and
      `ACP_ONLY_REASONS` is deleted, with its comment. Test: collecting the module under
      `-m "local_stack and runtime_claude_code"` selects the test, and under `runtime_acp` none.
