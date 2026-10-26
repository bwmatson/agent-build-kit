# Design

A node passes its model to the run entry point only when it is not empty, because a review's runner has its own and
because a runtime with no names means the agent's default. The entry point declares the model as required, so the two
disagree. The model becomes optional there, defaulting to empty, and the entry point passes an empty model on to the runtime,
which already treats it as selecting nothing.

The model is declared once, in the signature of the `run_agent` closure inside `build_run` in `pipeline/wiring.py`, and the
new-session, resume and continue paths all call it, so one change to that signature covers all three.

The test builds every node that runs an agent (tests, implement, fix checks, rework and adapt, and a continued session) over
the ACP runtime with all roles empty and a recorded agent, and asserts that each reaches the runtime and that none selects a
model. It goes through the real `build_run` closure and uses the recorded ACP agent in `tests/runtimes/acp_agent.py`: the fakes of the
run entry point in `tests/graph/agent_fakes.py` and `tests/graph/test_one_run_entry_point.py` declare `model` as required
themselves, so a test built on them would pass with the fault in place. It runs in the fast suite, so this cannot be found
only when live tests run.
