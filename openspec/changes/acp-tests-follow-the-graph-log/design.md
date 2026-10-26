# Design

## The tests

Replace the `step: (.*)` pattern with one built from the graph's node names
(`implement`, `review`, `rework`, `checks`, `push`, `open_pr`): a step line is
`<unit>: <node>: <message>`. "Review round" is the `review` node's message.
"First agent step" is the first of `tests` or `implement`. Progress lines keep
their shape: the unit id, a colon, then the runtime's indented line, found
between a step's first line and the next node's. The node names come from the
graph's enum, imported, so a rename changes the test with it.

## E2e-test's failure in the log

In the e2e-test node, on failure, the last lines of the report's output block are
written to the run log with the node's prefix. Bounded (the report is already
cut to its last 4,000 characters), and not repeated into the saved feedback.

## One line, once

The tick's per-unit logger already copies each line it is given into the unit's
run log, with a time. The graph's `say` gave a line to that logger and then
wrote it to the run log again, plain. Every node line therefore appears twice
in the log, and a test that counts pushes in it sees two for one. The fix is in
`say`, not in the test: the log should not carry duplicates.

## Order

Test first as usual: the three tests are the red state, and they are made to
pass. E2e-test is the proof, so this change's group is an e2e-test unit.

## Out of scope

The new end-to-end test of group 6, and any change to what the graph logs.
