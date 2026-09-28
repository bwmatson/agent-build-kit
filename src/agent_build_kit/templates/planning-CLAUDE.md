# Planning repo

This repo is the planning side of an `abk` workspace: the specs, the pipeline
state and the run logs for the code repos it builds ({repo_names}). No
application code lives here.

What lives where:

- `abk.yaml` — the workspace: which repos, where they are checked out, who
  owns them on GitHub, how each one deploys and tests. Every installation
  fact goes in this file and nowhere else; the framework itself knows
  nothing about any particular installation.
- `openspec/` — the OpenSpec project. `openspec/changes/<change>/` holds each
  change in flight (proposal, design, specs, tasks); `openspec/specs/` the
  specs that have shipped; `openspec/config.yaml` the context and rules the
  authoring model works from.
- `runs/` — pipeline state (`units.json`) and run logs. Read it; don't edit it
  by hand.
- `docs/unit_graph.md` — the unit graph, regenerated on every state change.
- `docs/recommendations/` — per-language tooling recommendations, researched
  at init and used when proposing changes.
- `systemd/` — the timer units that run the pipeline and the scheduled tracks.

`abk` runs this repo: `abk tick` is what the timer calls, `abk status` says
what is going on, `abk check` and `abk tags` validate a change before it is
committed. Three skills under `.claude/skills/` cover the rest:

- `abk-pipeline` — reading the pipeline's state and what to do about it.
- `abk-authoring` — writing a change's tasks so the pipeline can build them.
- `abk-config` — the `abk.yaml` schema and `abk doctor`.
