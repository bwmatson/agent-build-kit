# reconcile-host-moved-branch

When the pipeline finds a unit's branch on the host at a commit it did not
record, it should work out whether that commit is simply the same work, and
carry on, instead of failing the unit. Today a branch that was force-pushed by
a person, with the same change, fails the push as `StaleRemote` even though
review approved exactly that work.
