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
  tracks/          the scheduled health/improve/recommend/implement tracks and their prompts
  init/            abk init: detection, scaffolding, research, proposal
  recommendations/ built-in code-standard seeds per language
  templates/       what abk init writes into a planning repo
  skills/          the Claude Code skills abk installs into planning and code repos
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
  local_stack`. Test directories carry no `__init__.py`, so test file
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

## Running

```bash
uv sync --group dev
uv run poe test              # the suite (fixture-only, no node needed)
uv run poe test-integration  # needs node: runs the real OpenSpec CLI via npx
uv run poe test-local-stack  # tier 2: a real agent on this host (ABK_ACCEPTANCE_ACP_COMMAND), bills on demand
uv run poe format            # pre-commit: ruff, ruff-format, pyrefly, yamllint
uv run poe scrub             # the structural no-installation-leaks check
```

## Releasing

Bump `__version__` in `src/agent_build_kit/__init__.py`, add a `CHANGELOG.md`
entry, tag `vX.Y.Z`. Installations pin by editable path or by tag.
