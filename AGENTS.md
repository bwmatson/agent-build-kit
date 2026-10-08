# agent-build-kit

A framework: a spec-driven, unattended build pipeline that turns OpenSpec
changes in a **planning repo** into units of work, each one branch and one PR
in one of the workspace's **code repos**, built test-first by Claude Code,
reviewed, checked on two test tiers, verified live after merge, and archived.
Plus the scheduled health/improve/recommend tracks. `abk` is the CLI; `abk
init` sets an installation up.

This repo is the framework only. Everything about a particular installation —
which repos, who owns them, how they deploy, what their conventions are —
lives in that installation's `abk.yaml` and `openspec/config.yaml`, never here.

## This repo never names an installation

The one rule specific to this repo, and the reason it can be public:

- **No consumer references anywhere** — not in code, tests, prompts,
  templates, skills, docs or comments. No repo names, GitHub owners or slugs,
  product or service names, a product's config directory under the home
  directory, PR or issue numbers (a repo name, a hash sign and a number), or
  dated anecdotes about what happened in some installation. What an installation
  taught us is written as the general rule it revealed, not as the story.
- **Fixtures use neutral names.** Repos are `app` and `platform`; slugs are
  `example/app` and `example/platform`; services are `svc-a`, `svc-b`;
  changes are `feature`, `add-marker`. `example` is the reserved fixture
  owner.
- **Two checks keep it that way.** `tests/test_no_installation_leaks.py` is a
  structural check (home paths, non-fixture GitHub slugs, `word#number`
  anecdotes, product config paths, literal env keys) that runs with the
  suite. An installation runs `abk scrub-check --target <this checkout>`
  from its planning repo, which derives the forbidden terms from its own
  `abk.yaml` — the term list lives there, never here. Run both before
  merging.
- **Commits carry no `Co-Authored-By` trailer** in this repo.

## Code changes go through the spec process

This repo is built by the pipeline it contains, so a change to its **code**
(`src/`, `tests/`, the packaged prompts, skills and templates that shape agent
behaviour, dependencies) is made the way the pipeline makes any change, not by
an ad hoc session:

- **A code change is an OpenSpec change in the planning repo**: a proposal,
  delta specs, a design where there is a decision to record, and tagged task
  groups (see the `abk-authoring` skill). `abk check` and `abk tags` must pass
  before it is committed. The pipeline plans it into units and builds them
  test-first on `spec/<change>/<n>` branches; a person reviews and merges the
  pull requests.
- **An interactive session does not edit the code to make a change.** It may
  read, diagnose, and write or revise the change that describes the work. A
  session that finds a bug, wants a feature or sees a cleanup writes it up as
  a change (or a follow-up on one in flight) instead of patching the code.
- **The one exception is the pipeline itself being unable to run** — a defect
  that stops ticks, builds or the push gate, so a spec could not be built.
  That fix may be made directly, kept to what unblocks the pipeline, with its
  test, and recorded afterwards in the planning repo so the specs describe
  what the code now does.
- **Docs and other supporting files may be edited in a session**: `README.md`,
  `docs/`, this file, the changelog, and the like. When such an edit describes
  code a change is building, it still belongs in that change's tasks so the two
  land together.

## Layout

```
src/agent_build_kit/
  config.py        abk.yaml schema (pydantic, extra=forbid); config.active() for leaf modules
  installation.py  Installation: planning root, state/specs/graph paths, repos, verify env
  settings.py      machine-level settings from the environment and the planning repo's .env
  openspec.py      the OpenSpec CLI through npx, pinned by settings.openspec_version
  cli/             `abk`: each module exposes register(sub); func(args, installation)
  pipeline/        the unit pipeline: planner, work_graph, stack_runner, wiring, events,
                   gh_poller, restack, verify, archive, tier2, usage_guard, gate, ...
  hooks/policy.py  the Claude Code PreToolUse hook every agent run carries
  profiles/        toolchain profiles (python-uv today; node-npm declared)
  infra/           infrastructure profiles (docker, none): what a repo runs on
  tracks/          the scheduled health/improve/recommend/implement tracks and their prompts
  init/            abk init: detection, scaffolding, research, proposal
  recommendations/ built-in code-standard seeds per language
  templates/       what abk init writes into a planning repo
  skills/          the Claude Code skills abk installs into planning and code repos
web/               the web UI `abk serve` shows (React, TypeScript, Tailwind; Vite builds it into
                   src/agent_build_kit/serve/static, which is git-ignored and ships in the wheel)
tests/             mirrors src/ (tests/pipeline/test_<module>.py, tests/hooks/, ...);
                   tests/integration/ holds what needs node or the network (marked `integration`)
docs/              architecture, configuration, cli, toolchain-profiles, agent-runtimes, unit-graph,
                   init, tracks
```

## Conventions

- **Tests mirror the source layout.** A module's tests sit in the folder
  matching its package path; only the folder has to match, not the file
  name. Tests needing node or the network go under `tests/integration/`,
  marked `integration` (excluded by default). Tests driving a real agent on
  the host are tier 2: they live under `tests/integration/` too, are marked
  `local_stack`, are excluded by default and run with `uv run pytest -m
  local_stack`. Mark a test `serial` when it cannot share a process with
  others: `poe test` runs it in a serial pass after the parallel one, and
  `pytest <file>` runs without workers. Test directories carry no `__init__.py`, so test file
  basenames must be unique.
- **The habitat test.** `tests/integration/test_worktree_gate.py` commits a
  trivially correct file in a real git worktree of a fixture repository
  through the repository's own gate. It protects the worktree, the real
  gate, and the workspace layout a build depends on, and fails naming the
  hook when a checker matches no files or the linter rejects what the
  formatter produces. It is marked `integration`, so the default suite does
  not run it.
- **Tests reach a public surface.** A test imports no private name. Behaviour
  worth pinning is either given a name and a documented contract, or
  exercised through its caller.
- **Tests first.** A behaviour change lands with its failing test in the
  same change; the fixture repos are the tests' only installation.
- **Installation facts come from `Installation`/`config.active()`**, never
  from `__file__`, `Path.home()` product paths, or module constants. A new
  fact that differs per installation is a new field in `config.py` with a
  default, documented in the `abk-config` skill and `docs/configuration.md`.
- **A renamed setting keeps its old name working for one release.** An
  installation's `abk.yaml` is not in this repo, and the schema forbids
  unknown keys, so a rename that drops the old key stops every tick there the
  moment the installation updates — until someone edits the file by hand.
  Read the old key as the new one and log a warning naming both; refuse only
  a file that sets both. Say in the changelog which release drops it. A key
  removed outright is fine when no installation can be setting it yet, such
  as one added in the same unreleased version.
- **Toolchain facts come from the profile** (`profiles/`): commands, exit
  codes, what a test path is, what a stub may contain, prompt wording.
- **Types are pydantic models** (`model.Frozen`: frozen, `extra="forbid"`),
  not dataclasses. Env config is pydantic-settings (`settings.py`); no
  `os.environ` reads elsewhere.
- **Every shell-out to git and gh goes through `pipeline.shell`**, which
  selects the GitHub token for the repo's owner. The OpenSpec CLI goes
  through `openspec.py`.
- **Tool config lives in `pyproject.toml`** (ruff, pyrefly, pytest, poe);
  yamllint keeps `.yamllint` because it reads nothing else.
- **Prompts:** short format-string prompts stay as module strings beside the
  code that sends them; long playbooks (tracks, recommendations, skills,
  templates) are package data.

## Changelog (overrides the packaged text)

`CHANGELOG.md` opens with a `## Unreleased` section, and released versions follow it,
newest first. A pull request that changes what someone using the tool sees adds one
bullet under Unreleased, beside the bullets for related work, written for that person:
what changed and why, in plain words, wrapped with a two-space continuation. An entry
never names an installation, its repos or products, a pull-request or issue number, or
a dated story. Bullets are separated by one blank line, never run together, never
repeated, and never outside a `##` section. Add your bullet and leave the others as
they are, and never leave a conflict marker in the file. One change is one bullet, even
across several pull requests: fold later work into the bullet that already describes it
instead of adding another.

## Running

```bash
uv sync --group dev
uv run poe test              # the suite, fixture-only: parallel workers (capped at 8), then a serial pass of tests marked `serial`
uv run poe test-integration  # needs node: runs the real OpenSpec CLI via npx
uv run poe test-local-stack  # tier 2: a real agent on this host (ABK_ACCEPTANCE_ACP_COMMAND), bills on demand
uv run poe format            # pre-commit: ruff, ruff-format, pyrefly (from the lock), yamllint
uv run poe scrub             # the structural no-installation-leaks check
npm install --prefix web     # once: the web UI's dependencies
uv run poe web-check         # web/: prettier --check, eslint, tsc, vitest (`poe format` runs it too)
uv run poe web-build         # builds the web UI into the package, where `abk serve` serves it
```

## Releasing

Bump `__version__` in `src/agent_build_kit/__init__.py`, add a `CHANGELOG.md`
entry, tag `vX.Y.Z`. Installations pin by editable path or by tag.
