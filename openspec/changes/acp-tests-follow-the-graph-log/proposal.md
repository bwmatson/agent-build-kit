# Proposal

## Why

`tests/integration/test_acp_build_unit.py` drives a real unit through a real
agent and then reads the tick's run-log lines. It looks for `<unit>: step: …`
lines, among them "review round", "write the tests" and "implement", to check
the order of steps and that agent progress arrives inside a step. The graph
engine logs `<unit>: <node>: started` and `<unit>: <node>: <message>` instead.
Three of the file's five tests therefore fail, with `assert (None is not None)`
where the first step line is looked for.

The failure surfaced at e2e-test of `unit-graph` group 6, whose unit then spent
two attempts on it. The acceptance unit's job is the new end-to-end test, not
repairing earlier tests the cutover left behind, and a rework that is handed a
long report of someone else's failure does not find its way to them.

A failing e2e-test also leaves its output only in the unit's saved feedback, not
in the run log, so a person reading the log sees "e2e-test failed" and nothing
else.

## What Changes

- **The three tests read the graph engine's log.** Step order, the review round
  and the agent's progress lines inside a step are found by the graph's
  `<unit>: <node>: …` format. What they prove stays the same.
- **The log format is a stated contract for these tests**, not an accident
  they happen to match: the node names they rely on are the ones the graph
  defines.
- **A failing e2e-test writes the tail of its output to the run log**, besides
  saving it as the unit's feedback.
- **`unit-graph` group 6 waits for this to merge**, so its unit starts on a
  green live-agent suite.
