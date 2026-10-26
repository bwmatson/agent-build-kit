# needs-start-on-the-parents-branch

Removes the `merged` qualifier of the `Needs:` line. A `Needs:` line is a dependency that starts
the dependent on the parent's reviewed branch, as any same-repo dependency does; the merge gate,
the trunk start and the `merged` edge label go. A cross-repo parent still has to merge, because it
cannot be stacked on.
