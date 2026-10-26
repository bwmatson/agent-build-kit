# tracks-leave-the-planning-repo-on-its-branch

A scheduled track's agent created a feature branch in the planning repo instead
of in the code repo it was working on, and the planning repo stayed on that
branch. The runner, not the agent, should commit a track's bookkeeping, and the
planning repo should be checked and put back on its default branch after every
phase and before every tick.
