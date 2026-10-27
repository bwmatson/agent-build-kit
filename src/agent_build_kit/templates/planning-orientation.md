## Planning

This repository is also its own planning repo: the specs, the pipeline state and the
configuration live here beside the code, and the pipeline builds changes into it.

- `{prefix}abk.yaml` — the configuration: the repos, how each one builds, tests and deploys.
- `{prefix}{specs_dir}/` — the OpenSpec project. `{prefix}{specs_dir}/changes/<change>/` holds
  each change in flight; `{prefix}{specs_dir}/specs/` the specs that have shipped.
- `{state_dir}/` — the pipeline's state (`units.json`) and run logs. Read it; don't edit
  it by hand.
- `{graph_page}` — the unit graph, regenerated on every state change.

The specs are written in this repository by the pipeline and by `abk`, so expect commits that
touch only the specs. The state may be outside the repository and is not committed.

Write a change under `{prefix}{specs_dir}/changes/` in your working copy and commit it. A
session does not edit the code to apply a change: the pipeline builds it. Ticks and tracks run
in the pipeline worktree that `abk install-timers` makes; from the working copy the command is
`abk --config <worktree>/abk.yaml tick`, and `abk status` prints it.
