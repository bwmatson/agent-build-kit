# independent-groups

Let a task group say it does not depend on the groups before it, so the
pipeline builds it in parallel with them instead of after the unit before it.
Today every unit of a change depends on the one before, so independent work in
another repo waits for work it does not need, or has to be split into its own
change.
