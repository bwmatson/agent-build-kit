# agent-build-kit

A spec-driven, unattended build pipeline for Claude Code across a workspace
of repos. Changes are written as OpenSpec changes in a **planning repo**; the
pipeline turns each change's task groups into units of work — one branch and
one pull request each, in one of the workspace's **code repos** — builds them
test-first with Claude Code, reviews them with a second model, runs two test
tiers, pushes only what review approved, and after a human merges everything
deploys the change, runs its live tests and archives the spec. Scheduled
tracks (health, improve, recommend) keep watch on the repos in between.
`abk` is the CLI; `abk init` sets an installation up.

## Status

Early. No licence has been granted yet: all rights reserved, and a licence
will be chosen later. The `python-uv` toolchain profile is implemented; the
`node-npm` profile is declared but not implemented (see
[docs/toolchain-profiles.md](docs/toolchain-profiles.md)).

## The shape

```
 planning repo                      code repos                    its host
 ─────────────                      ──────────                    ──────
 openspec/changes/<change>/   ──►   worktree per unit     ──►     PR per unit
   tasks.md (tagged groups)         tests commit, then             (never merged
 abk.yaml (the installation)        implementation,                by the agent)
 runs/units.json (the state)        review loop, tier 1,                │
        ▲                           tier 2 on the dev stack             │
        └──────── poll: merged / closed / rework / restack ◄────────────┘
                  then verify (deploy + live tests) and archive
```

- The **planning repo** holds the specs (an OpenSpec store), `abk.yaml`
  (everything about this installation: repos, owners, deploy rules, limits)
  and the pipeline's state. No application code lives there.
- The **code repos** are ordinary checkouts. Each unit gets its own git
  worktree outside every repo; the agent writes there and nowhere else.
- **Claude Code** is the runtime for every agent step, always headless
  (`claude -p`), always under a policy hook that denies merging, force-pushing
  without an explicit lease, and writing outside the unit's worktree.
- Everything runs **unattended** from a timer. A tick is safe to run at any
  moment; the state on disk is what carries a unit from one tick to the next.

## Quick start

The planning repo is a small `uv` project with the framework as a dependency.

```bash
mkdir planning && cd planning
uv init --bare
uv add --editable ../agent-build-kit     # or a git dependency, pinned by tag
uv run abk init . --repo ../app --repo ../platform
```

`abk init` detects each repo, drafts `abk.yaml`, lays out the planning repo
(OpenSpec store, state directory, systemd units, skills), researches a
tooling-recommendations document per language and asks a model to write each
repo's first changes. Then:

```bash
uv run abk doctor                        # is this installation runnable?
uv run abk tick --dry-run                # what would build now
cp systemd/abk-tick.* ~/.config/systemd/user/ && systemctl --user enable --now abk-tick.timer
```

Requirements: Python 3.12+, `uv`, `git`, and a client for each host a repo
lives on: `gh` (logged in for every GitHub
owner in `abk.yaml`), `claude` (Claude Code), and `node` on the PATH — the
OpenSpec CLI runs through `npx`.

## Commands

| Command | What it does |
|---|---|
| `abk init [dir] --repo PATH ...` | Create a planning repo for a set of checkouts. |
| `abk doctor` | Check the installation: repos, accounts, toolchain, config drift. |
| `abk config [--show\|--path]` | The effective `abk.yaml` with defaults filled, or its path. |
| `abk tick [--dry-run] [--only UNIT]` | One pass: usage, poll, plan, verify, archive, build. |
| `abk status` | What the pipeline thinks is going on. Changes nothing. |
| `abk graph` | Regenerate the unit graph page. |
| `abk verify CHANGE` | Deploy a merged change, run its live tests, archive it. |
| `abk tags [CHANGE\|--all]` | Validate a change's task-group tags. |
| `abk check` | `openspec validate --all --strict --json`. |
| `abk archive CHANGE` | `openspec archive CHANGE --yes`. |
| `abk openspec -- ARGS` | Any OpenSpec command, in the planning repo. |
| `abk gate [--repo] [--base]` | The tests-first gate for a branch: commit order, clean, red. |
| `abk install-skills [--repo PATH] [--user]` | Copy the abk skills into `.claude/skills/`. |
| `abk scrub-check --target DIR` | Grep a checkout for anything naming this installation. |
| `abk track PHASE [--project NAME]` | Run a scheduled track (health, improve, recommend, implement) now. |

Details, arguments and exit codes: [docs/cli.md](docs/cli.md).

## Documentation

- [docs/architecture.md](docs/architecture.md) — the whole flow, the guards, the state on disk, and why it is shaped this way.
- [docs/configuration.md](docs/configuration.md) — the `abk.yaml` schema, env providers, environment variables.
- [docs/cli.md](docs/cli.md) — every subcommand.
- [docs/toolchain-profiles.md](docs/toolchain-profiles.md) — what a profile is, what `python-uv` runs, what `node-npm` still needs.
- [docs/code-forges.md](docs/code-forges.md) — the hosts a repo can live on, what each makes easy to get wrong, and how to add one.
- [docs/init.md](docs/init.md) — what `abk init` does, step by step.
- [docs/tracks.md](docs/tracks.md) — the scheduled health/improve/recommend/implement tracks.

Contributing conventions are in [CLAUDE.md](CLAUDE.md). One rule matters
more than the rest: this repo never names an installation — no repo names,
owners, product names or anecdotes from any deployment.

## Acknowledgements

- **OpenSpec** (MIT, by Fission-AI) is the spec store and the CLI the
  framework drives through `npx`: the `@fission-ai/openspec` package,
  https://github.com/Fission-AI/OpenSpec. Changes, delta specs,
  validation and archiving are OpenSpec's; the framework adds the task-group
  tags, the planner and the build pipeline around them.
- **Claude Code** is the agent runtime: every build, review, rework, planning
  and research step is a `claude -p` call.
