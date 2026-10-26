# a-unit-waits-for-all-but-one-open-parent

A unit that would stack on two or more open pull requests that do not build on each other now waits until at most one of them is still open,
instead of starting on one parent's branch and silently lacking the other's changes. The scheduler reads the wait from `waiting_on`, so the
status, the graph, `ready_units` and the counting of blocked units all give one answer, and `abk tags` and `abk check` warn when a change's
task groups will produce such a unit. No branch is built from several parents; the unit simply waits.
