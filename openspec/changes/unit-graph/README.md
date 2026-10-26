# unit-graph

Move a unit's lifecycle onto LangGraph: one thread per unit carries its steps,
checkpoints, waits for review and resume after a kill, and the poller's events
reach a unit as resume commands. Choosing what starts, the tick, polling,
locks and all git and forge work stay as they are. The design is
`docs/unit-graph.md` in agent-build-kit; this change implements it.
