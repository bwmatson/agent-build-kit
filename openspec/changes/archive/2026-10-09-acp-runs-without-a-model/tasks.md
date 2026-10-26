# Tasks

Acceptance: none — the fast suite drives every node over the ACP runtime with a recorded agent; the live tests that found
this stay as they are.

## 1. [agent-build-kit] [tier1] Nodes run when the model is empty

Done when every node that runs an agent runs on a runtime that names no models.

- [x] 1.1 Test: built through the real `build_run` closure in `pipeline/wiring.py` (not the fakes in `tests/graph/agent_fakes.py` or
      `test_one_run_entry_point.py`, which declare the model required and would hide the fault), over the ACP runtime with
      every role empty and `tests/runtimes/acp_agent.py` as the recorded agent, the tests, implement, fix-checks, rework and
      adapt nodes and a continued session each reach the runtime with no model selected, and none fails with a missing
      argument.
- [x] 1.2 Test: over the Claude Code runtime a node still runs on the model for its role.
- [x] 1.3 Make the model optional in the one signature of `run_agent` inside `build_run`, which the new-session, resume and
      continue paths all call, and pass an empty model through.
- [x] 1.4 Add a changelog entry.
