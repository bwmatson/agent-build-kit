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
- whether it is a git checkout, its GitHub slug from `origin` (ssh, https,
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

`--dry-run` prints this `abk.yaml` and the list of what would be generated,
then exits 0.

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
| `systemd/` | 8 units: `abk-tick`, `abk-track-health`, `abk-track-improve`, `abk-track-recommend`, each a `.service` and a `.timer`, with the planning directory filled in |
| `.claude/skills/*/SKILL.md` | the three skills, version-stamped |

Whether or not `abk.yaml` was written is printed (`kept abk.yaml (use
--force to overwrite)`).

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
the timers from `systemd/`.

## Idempotence and `--force`

Running init again over the same planning repo is safe: the layout writes
only what is missing, the recommendation documents and generated changes are
kept, and `abk.yaml` and `openspec/config.yaml` — the two files a person
edits — are never overwritten. `--force` overwrites all four kinds. `abk
doctor` is the other half: it re-runs detection to report where `abk.yaml`
has drifted from the checkouts, and where `openspec/config.yaml`'s rules
have drifted from the framework's template.

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
