# acp-tests-follow-the-graph-log

The live-agent tests that read a unit's run log still expect the old engine's
`step: …` lines. Since the graph became the only engine they fail at e2e-test,
which blocked `unit-graph` group 6. This change brings them up to date, and
makes a failing e2e-test write its failure to the run log, as a prerequisite so
the unit that proves the graph end to end does not also have to repair them.
