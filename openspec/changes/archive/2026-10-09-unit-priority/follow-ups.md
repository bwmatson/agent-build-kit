## From `unit-priority/2`

- Scope note for whoever reviews this PR: this branch puts the priority sort in `ready_units`, and the design gave that sort to `start-order-by-stack-age`. The planning repo should record that tasks 1.6 and 1.7 of `start-order-by-stack-age` now build on a sort that already exists. Otherwise that change will write the same `sorted(...)` call a second time.
