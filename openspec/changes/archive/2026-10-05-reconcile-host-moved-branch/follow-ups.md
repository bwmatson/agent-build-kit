## From `reconcile-host-moved-branch/1`

- restack.adopt_host_head's dirty check passes an untracked file that `reset --hard host_head` would overwrite because the host head tracks the same path. Either refuse that collision as well or document that it is not covered.
- src/agent_build_kit/pipeline/restack.py:497 — The dirty-worktree check skips untracked files (`--untracked-files=no`). But `reset --hard host_head` silently overwrites an untracked file whose path the host head tracks, so an untracked file is not always safe from the reset.
