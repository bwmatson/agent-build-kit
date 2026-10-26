# a-unit-in-a-held-split-is-not-started

A unit whose e2e tests are in a held split is not started while the split is held. Today such a unit starts, builds, spends model usage on
implementation, review and the part of tier 2 that can run, and then parks at tier 2 because the held part cannot; the usage on the part that
could run is wasted, since the unit cannot be cleared until the split is released. Here a task group says which split its tests are in
(`Split: <name>`), one split to a group, a unit never carries groups of two splits, and a planned unit whose split is held is not started and
not counted, and is started by the round that sees the hold released. A test that must run in two splits is written as two groups: the part in
no held split merges now and the held part waits. The parking of a unit already started stays as the backstop.
