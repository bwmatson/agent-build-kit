## Planning

This repository is also its own planning repo: the specs, the pipeline state and the
configuration live here beside the code, and the pipeline builds changes into it.

- `abk.yaml` — the configuration: the repos, how each one builds, tests and deploys.
- `{specs_dir}/` — the OpenSpec project. `{specs_dir}/changes/<change>/` holds each change in
  flight; `{specs_dir}/specs/` the specs that have shipped.
- `{state_dir}/` — the pipeline's state (`units.json`) and run logs. Read it; don't edit it by
  hand.
- `{graph_page}` — the unit graph, regenerated on every state change.

The specs and the state are written in this repository by the pipeline and by `abk`, so
expect commits that touch only these paths.
