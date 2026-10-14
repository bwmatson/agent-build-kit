# `abk init`

`abk init` creates an installation: a planning repo for a set of checkouts.
It is the one command that writes `abk.yaml` rather than reading it.

```bash
uv run abk init . --repo ../platform --repo ../app
```

## Step by step

### 1. Detect

For each `--repo` path (or each path typed at the prompt, one per line, when
none is given and `--yes` is not), `init/detect.py` reads what it can off the
checkout without asking anyone:

- the name: the directory name (two repos with the same name is an error);
- whether it is a git checkout, which forge `origin` names and its identity
  there (ssh, https,
  `ssh://` and ssh-alias forms), and its default branch from
  `origin/HEAD` (else `main`);
- whether it **has code**: at least one commit and a tracked file that is not
  a lockfile, `pyproject.toml`, `package.json`, `.gitignore`, a README, a
  LICENSE, a `.md`, or under `.github/` or `docs/`;
- its languages and profile: `pyproject.toml`/`uv.lock`/`setup.py`/
  `requirements.txt` → `python`, profile `python-uv`; `package.json` →
  `javascript` (plus `typescript` with a `tsconfig.json`), profile `node-npm`
  unless Python was found first;
- service directories: top-level directories holding a `Dockerfile`,
  `pyproject.toml` or `package.json`;
- a dev-stack script at `scripts/dev-stack.sh`, and the `<NAME>_CREDENTIALS=(`
  shell array in it, if any;
- dependency references: git URLs in `[tool.uv.sources]` and package specs in
  `package.json`, from which `consumes` is resolved — a repo consumes every
  other workspace repo whose slug appears among them. `--consumes
  app:platform` overrides this per repo.

Everything detected is a guess a person reviews in the generated file.

### 2. Draft

`draft_config` turns the detections into a `WorkspaceConfig`: repos in
consume order (consumed first), each with its path, slug (or
`todo-owner/<name>` when there is no origin), default branch, profile,
languages, `consumes`, a `dev_stack` when the script exists, `credentials`
when the array was found, and one empty deploy rule per service directory
(`prefix: svc-a/`, `run: []`) for the person to fill.

`--dry-run` prints this `abk.yaml` (with the runtime choice below) and the
list of what would be generated, then exits 0.

### 2a. Choose the runtime

Before anything is written, and before any agent step, init decides which
agent runtime runs. Nothing in this step calls a model.

- **The probe.** Each runtime reports the candidates it finds on this machine
  (`detect`): the program on the path, the optional library, and for an agent
  whose flag varies one `--help` run with a 5 second timeout. The usable ones
  are listed first, each unusable one with its reason, and the last line is
  always "Other / my own configuration". With exactly one usable candidate
  Enter takes it; with several there is no default.
- **The runtime's own questions** (`setup_questions`), in order, each with a
  default Enter accepts and a validator that re-asks on a bad answer (a
  program that is not on the path, an empty command). `back` returns to the
  list. Init holds no per-runtime code: a runtime added later brings its own
  questions and their answers are written where each says.
- **What the agent needs.** A candidate whose table entry says it needs
  something (a running gateway, an API key) is asked whether that is in place
  and, if not, whether to continue anyway.
- **Models.** Asked only without `--yes`, from what needs no model call: the
  models the agent advertises when a session opens (with its current one
  marked default and listed first), Claude Code's documented aliases (one
  question first: `1` the default models, `2` choose per role, `3` type names),
  or, for an agent that lists none, a typed name that is not checked now. The
  choice lands under `models:`; an empty role is the agent's own default.
- **A fallback.** When another runtime is usable, init offers to configure it
  too under `runtimes:`; `runtime:` still names the first. Declining its needs
  leaves it out.
- **The confirmation.** Init prints the `abk.yaml` fragment it will record and
  asks `[Y/n]`. A no writes nothing and exits 1. `--yes` is the confirmation
  for a fully specified run.

The same answers can be given without a prompt: `--runtime NAME`,
`--agent-command ARGV`, repeatable `--set key=value` (the key is where the
answer is written, e.g. `models.review`) and `--runtime-config FILE` (a YAML
fragment of `abk.yaml`). Every route is validated like a typed answer and an
unknown key exits 2 naming it, also on a kept `abk.yaml`. With `--yes`, a
single usable runtime is taken; none, or several without `--runtime`, exits 2
and writes nothing. A kept `abk.yaml` that names a runtime skips the step;
`--runtime` overrides it after a confirmation or with `--force`.

### 3. Write

`write_planning_repo` lays the planning repo out. Every file is written only
if missing, so a second run over an existing planning repo fills gaps and
changes nothing else:

| Written | Notes |
|---|---|
| `.git/` | `git init -b main` when absent |
| `openspec/` | `openspec init --tools claude --no-animation` when absent |
| `abk.yaml` | the draft, defaults left out. Overwritten only with `--force` |
| `openspec/config.yaml` | `schema: spec-driven`, a `context:` describing the repos and cross-repo conventions, and the framework's per-artifact `rules:` for the authoring model (tagged headings, GIVEN/WHEN/THEN scenarios, `[contract]`/`[narrow]`/`[acceptance]`, tests before implementation) headed `# abk-rules: v1`. Overwritten with `--force`, or when it is still the stock file `openspec init` wrote (only a `schema` key) |
| `runs/.gitkeep`, `runs/units.json` | the state directory and an empty unit store |
| `.gitignore` | `.env`, `.last-runs/`, `runs/*.lock`, `runs/locks/`, local tooling |
| `.env.example` | every machine-level variable, commented out |
| `CLAUDE.md` | what lives where in a planning repo, and the three skills |
| `.claude/skills/*/SKILL.md` | the three skills, version-stamped |

Whether or not `abk.yaml` was written is printed (`kept abk.yaml (use
--force to overwrite)`).

#### The code repos' changelog conventions

`write_code_repo_conventions` then does three things in each listed repo whose
checkout exists and whose `changelog` setting is on (read from the `abk.yaml`
that stands, so a kept file that sets `changelog: null` for a repo is
respected). Nothing is committed in the code repos; the change is left in the
working tree for the person to review.

| Action | What it does |
|---|---|
| block | appends the changelog convention to `AGENTS.md`, else `CLAUDE.md`, else a new `AGENTS.md`, between `<!-- abk:changelog vSTAMP -->` and `<!-- /abk:changelog -->` markers, keeping the file's line endings |
| changelog | creates the configured changelog (`# Changelog`, `## Unreleased`) when absent; an existing one is never edited |
| gitattributes | adds `<changelog> merge=union` to `.gitattributes`, creating the file or adding a final newline as needed |

A second run changes nothing. A block whose stamp or body differs from the
packaged text has only the text between its markers replaced. A repo with its
own `## Changelog` section outside the markers gets no block, mismatched
markers are reported and left alone, and a `.gitattributes` that already sets
another `merge=` driver for the changelog is reported and left. To opt a repo
out, set `changelog: null`; all three actions are skipped. `abk doctor` warns
about a repo with a changelog and no union rule. `--dry-run` prints one line per
repo and action.

The acceptance run is the real `abk init` over a scratch workspace of three code
repos (one with an `AGENTS.md`, one with only a `CLAUDE.md`, one with neither),
checking each repo's files and `git status`, then running it again to see that
nothing changes. It needs node for the OpenSpec CLI and no agent. Run it with
`uv run pytest -m local_stack tests/integration/test_init_conventions_workspace.py`.

### 4. Research

For each language detected across the workspace (`typescript` folds into
`javascript`), `init/research.py` writes
`docs/recommendations/<language>.md` — kept if present, unless `--force`;
skipped entirely with `--skip-research`.

The framework ships a **seed** for `python` and `javascript`
(`recommendations/*.md`): a starting position with sections Formatting,
Linting, Types, Test layout & tiers, Packaging & workspaces, Configuration &
types conventions, Pre-commit, CI, each item stating the rule, the tool and
its version floor, the rationale, and how to verify a repo follows it. A
`claude -p` run with `Read Grep Glob WebSearch WebFetch` validates every item
against current practice on the day init runs — keep, amend or drop with a
source, settle the items marked *to be decided by research*, add what is
missing. A language with no seed gets a document in the same structure from
scratch. The output is written with a dated header and a `## Sources`
section (a warning stands in when the model left none out).

### 5. Propose

For each repo with a detected language — skipped with `--skip-propose` —
`init/propose.py` asks a model to write the repo's first changes under
`openspec/changes/`, one per **kind**:

| Change | When | What it specifies |
|---|---|---|
| `<repo>-testing-infrastructure` | the repo has code | test runner and layout, markers/tiers, fakes at protocol boundaries, a tests-first gate, CI — so an agent can change the repo safely |
| `<repo>-code-standards` | always | types, formatting, linting and best practices from the language's recommendations, applied to this repo |

An existing change directory is kept unless `--force`. The run happens in the
planning repo with the code repo mounted read-only (`--add-dir`), tools
`Read Grep Glob Write Edit Bash(ls*)`, and the policy hook with the specs
fence dropped (its whole job is to write under `openspec/changes/<change>/`;
the command policy and the worktree write fence stay). The prompt carries the
heading contract, the rendered `rules:`, a summary of the repo (top level,
the first 60 lines of `pyproject.toml`, `package.json`,
`.pre-commit-config.yaml` and each workflow) and the recommendations
document.

The result must pass what a hand-written change passes: `openspec validate
--all --strict --json` and `abk tags`. The model gets **one repair round**
with the errors; a second failure is reported, the files are left in place
to finish by hand, and init exits 1 at the end.

### 6. Register, commit, next steps

`--register-store ID` runs `openspec store register --id ID --yes` on the
planning repo. Then, if the planning repo's tree was clean *before* init ran,
everything is committed as `abk init: workspace <names>`; otherwise nothing
is, and the reason is printed. Finally the next steps: review `abk.yaml`
(fill each `deploy.rules[].run`, `description`, `relationships`; replace any
`todo-owner/` slug), set a repo-local git identity in each checkout, log `gh`
in for every owner, copy `.env.example` to `.env`, run `abk doctor`, install
the timers with `abk install-timers`.

### Notifications

On WSL or Windows (and not with `--yes`), init asks `raise desktop notifications when a unit
needs you?`. A yes sets `notifications.provider: windows`, prints the install command for the
BurntToast module, and asks `install it now?` before running it. The command is pinned to the
module release the toast scripts are written for (`BURNTTOAST_VERSION`, 0.8.5) and passes
`-Force` so PowerShell does not stop at its NuGet and untrusted-repository prompts, which the
captured output would hide; a failure prints the command's exit code and stderr. Other hosts
are asked nothing. An `abk.yaml` that is kept is asked nothing either, since init only fills
it; set `notifications` by hand there.

## The environment section

Init is the only place that guesses an `environment` section. It asks the
toolchain profile repository detection chose, then the other registered
profiles in order, to draft it from the marker files in the planning repo and
in each code repo (for Python a manifest and its lock file; where the manifest
names path sources, the inputs still hold only the repo's own manifest and lock,
since patterns stay in the repo, and `check` becomes `sh -c "uv lock --check &&
uv sync --check && <import check>"` so a change in a checkout it points at fails
the check and the next tick syncs, with a comment above the section saying why;
for node a `package.json`,
its lock file and `workspaces`, with the dependency directory as an artifact).
The first profile to propose a section wins, and it writes a `sync` command,
a `check`, and the manifests and lock files found. The lock files
are also written into `global_limits.generated_files`. Where it recognises nothing
it writes the planning section with empty commands and says to set them by
hand; configuration refuses empty commands until then. A code repo it does
not recognise gets no section, and `abk doctor` warns.

Over an existing `abk.yaml` init fills what is missing and nothing else: the
planning section, each listed repo's section and `global_limits.generated_files`.
Every existing line stays as it is, comments included: the missing parts are
added as text. A section already present is never changed. The dry run over
an existing file lists each part it would fill, with its YAML, instead of a
whole file.

## The policy step

After `abk.yaml` is written, init checks that the selected runtime refuses the
command classes abk forbids, the way `abk policy check` does: it reads the
agent's own configuration, starts no agent and asks no question about tokens.
The answer is labelled "what the configuration says, in abk's dialect; not
observed from the agent". For a class it does not refuse, init offers a fix in this
order: the installation's `runtimes.<name>.policy_fix`; else, for a known agent
the kit can write to, the kit's recommended policy (the configuration path and
the diff are shown, init asks, applies the deny list only and checks again);
else the choices of the unknown-agent menu, which names `abk policy patterns`.
`--yes` runs neither kind of fix unless `--run-policy-fix` is also given.
`abk init --policy-only` runs just this step. The details are under `abk init`
in [cli.md](cli.md).

## Idempotence and `--force`

Running init again over the same planning repo is safe: the layout writes
only what is missing, the recommendation documents and generated changes are
kept, and `abk.yaml` and `openspec/config.yaml` — the two files a person
edits — are never overwritten. `--force` overwrites all four kinds. `abk
doctor` is the other half: it re-runs detection to report where `abk.yaml`
has drifted from the checkouts, and reads the `# abk-rules:` stamp in
`openspec/config.yaml` to report what the framework has added to its rules
since that version. The rules themselves are yours to reword; only the stamp
is compared. `abk init --update-rules` closes the gap without rewriting
anything: it adds each newer version's paragraph to the end of the `context:`
and restamps the file, leaving every other line as it was.

## Adding a project later: `abk project init`

`abk init` records the projects it finds. A project that does not exist yet is added
with `abk project init <path> --profile <name> --repo <repo>` (see `docs/cli.md`), which
writes the same `projects:` entry into `abk.yaml` without touching its comments, and
with `--scaffold` the minimal manifest that detection recognises as that profile's.

## `install-skills` and the three skills

`abk install-skills` copies `skills/*/SKILL.md` into `.claude/skills/` — of
the planning repo and every checkout by default, of `--repo PATH`, or of the
user-level directory with `--user`. Installing stamps the framework version
into the `generatedBy: agent-build-kit <version>` header; that header is how
`abk doctor` tells a stale copy from a current one, and how the installer
tells its own file from one somebody wrote by hand under the same name, which
it refuses to overwrite.

| Skill | Triggers when an agent is... |
|---|---|
| `abk-authoring` | writing or editing a change's `tasks.md`, choosing `[repo] [tier]` tags or `[contract]`/`[narrow]`/`[acceptance]` flags, or reading an `abk tags` error. The heading contract, the flags, `Needs:` lines, `abk check`/`abk tags` before committing. |
| `abk-config` | editing `abk.yaml`, reading an `abk doctor` report, or asked where an installation fact should live. The schema, what doctor checks, how to add a repo or a service. |
| `abk-pipeline` | asked what the pipeline is doing, why a unit is stuck, what `held`/`failed`/`in_review` mean, or about to run `abk tick`, `abk verify` or `abk archive`. The commands, the state files, the unit states and what to do about each, a change's lifecycle, pauses. |
