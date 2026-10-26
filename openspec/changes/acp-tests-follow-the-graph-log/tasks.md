# Tasks

Acceptance: none — the live-agent suite passing at e2e-test is the proof of this
change; there is no consumer surface beyond it.

## 1. [agent-build-kit] [e2e-test] The live-agent tests follow the graph's log

Done when `tests/integration/test_acp_build_unit.py` passes against the graph
engine at e2e-test and a failing e2e-test leaves its output tail in the run log.

- [x] 1.1 Test (`local_stack`): the three failing tests in
      `tests/integration/test_acp_build_unit.py` read steps as
      `<unit>: <node>: …` using the graph's node names, find the review round,
      the first agent step and the progress lines inside it, and pass.
- [x] 1.2 Test: a unit whose e2e-test fails writes the tail of the failing output
      to its run log.
- [x] 1.3 Update the three tests, importing the node names from the graph.
- [x] 1.4 Write e2e-test's failure tail to the run log in the e2e-test node.
- [x] 1.5 Compare `docs/unit-graph.md`'s testing section with this and change
      whatever no longer matches, or say in the pull request that nothing
      differs.
- [x] 1.6 Test: a node's progress line appears once in the unit's run log, not
      twice: the tick's logger already copies every line into the run log with
      its time, and `say` wrote it a second time without one. A push is logged
      once, so the log's pushes match the branch's reflog.
- [x] 1.7 Make `say` log through the tick's logger only when a run log is
      attached to it, and write to the run log directly only when it is not.
