# fresh-base-before-push

A unit checks its base against the remote, deterministically, before every run
that starts from existing commits and again before every push. If the base has
moved it rebases first; a clean rebase costs no agent call. A base that has
disappeared by the time the pull request is opened holds the unit for a
restack instead of failing it.
