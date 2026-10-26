## From `needs-gate-started-units/1`

- The 1.2 test in tests/graph/test_graph_tick.py now checks the real thread. Its `spy` still reads the requeue reason from the arguments passed to `resume_thread`. A stronger version would read the reason from the thread's own event history, if the graph exposes one, so the assertion would not depend on the CLI-side call.
