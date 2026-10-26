# split-stack-depth-caps

Rename `stack_depth_cap` to `stack_depth_build_cap` — it only ever gated whether a new unit may
start — and add `stack_depth_rebase_cap`, defaulting to the same value, that bounds how far up a
stack the pipeline will automatically rebase a dependent when the unit beneath it merges.

Today the two are the same cap wearing two hats, and that is an accident of there having been only
one knob. A chain deep enough to be worth building is not always a chain worth auto-cascading a
conflict resolution through on every merge.
