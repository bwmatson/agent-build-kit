# needs-merged

Let a `Needs:` line say the dependency must **merge** before the dependent
starts, whatever repo either is in. Today a same-repo dependency only has to
reach review, and the dependent then stacks on its branch. That is right for
most work, but not for a change that is built on top of what an earlier change
is still reshaping.
