# open-pr-ceiling

Stop starting new units once there are too many pull requests open: a configurable
ceiling, default 5, counted across the workspace.

The concurrency cap bounds how many units build at once. Nothing bounds how many
finished units sit waiting — and waiting is not free: every merge beneath an open
pull request buys it a rebase, a conflict resolution and another review round, all
of them agent runs. The cost of a queue is paid in tokens, and it grows faster than
the queue does.

And when slots are free, work that already exists goes first: a unit with an open
pull request to rework, then a unit paused part-way through its build, then a new
one. Today the order is whatever order units were planned in.
