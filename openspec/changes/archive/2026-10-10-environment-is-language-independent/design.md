# Design

## What was verified against the code

- `EnvironmentConfig` has `sync` and `check` argv lists and `inputs` with `dependencies`, `lock` and `other`.
  `inputs_hash` (in the pipeline's environment module) reads each listed name as `root / name` and, when it is
  not a file, records `<missing>`. `_changed_from_base` compares each literal name against the base with
  `git rev-parse <point>:<name>`. Both are literal-path only.
- `generated_file_patterns` in the configuration returns the explicit `limits.generated_files` plus the final
  path component of every configured lock path. **Correction to the brief:** the hard-coded list of lock file
  names no longer exists. `limits.generated_files` defaults to an empty tuple. The stale spot is
  `docs/configuration.md`, whose example shows `generated_files: [uv.lock, package-lock.json, ...]` beside the
  words "none by default". What to keep: the explicit list, for generated files that are not locks (generated
  sources, snapshots); nothing built in. The lock-derived entries are already redundant with `inputs.lock`, so
  no second list is wanted. With patterns, the derivation takes the final component of a lock pattern, which for
  `**/package-lock.json` is the file name as today; a pattern whose final component is itself a glob is used as
  written.
- `abk init`'s `detect_environment` (in `init/environment.py`) knows `pyproject.toml`, `uv.lock` and the manifest's
  path sources, and proposes `uv sync` and a `uv run` check. `profiles/node_npm.py` has detection markers
  (`package-lock.json`, `package.json`) but every method that would build refuses with `ProfileUnsupported`;
  `abk init` writes empty commands for a node repository.
- The pieces that make lock files pipeline-owned (the dirty check ignoring them, the commit step's rules) are the
  running change `environment-sync-leaves-no-leftovers`. This change extends them and does not restate them.

## Group 1: the rule and the check

### The offender search

Searched `src/agent_build_kit/**/*.py` outside `profiles/` and `init/` for these tokens, as whole words and
not as part of a hyphenated name: `uv`, `pip`, `poetry`, `npm`, `npx`, `pnpm`, `yarn`, `cargo`; and the names
`uv.lock`, `pyproject.toml`, `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `poetry.lock`,
`Cargo.lock`, `requirements.txt`. Result: **26 matches in 9 files**, none a lock file name.

| File | Matches | What | Disposition |
|---|---|---|---|
| `cli/doctor.py` | 12 | node/npx presence for the OpenSpec CLI (3); a check of `uv run` hook entries against `pyproject.toml` dependency groups (9) | Allowlisted. The hook check is Python-toolchain knowledge that belongs behind a profile; it moves when a profile hook for repository health checks is specified. The npx lines are framework tooling (below) |
| `tracks/runner.py` | 1 | `Bash(uv run *)` in the tracks' tool allowlist | Allowlisted; should come from the profile's `allowed_tools` |
| `pipeline/wiring.py` | 2 | docstrings naming `uv` and `uv run pre-commit` | Reworded in group 1; no allowlist entry |
| `runtimes/acp.py` | 1 | a comment naming `pyproject.toml` | Reworded in group 1; no allowlist entry |
| `openspec.py` | 3 | the OpenSpec CLI is run through `npx` | Framework's own tooling, listed as such |
| `serve/server.py` | 2 | the web UI is built with `npm` | Framework's own tooling, listed as such |
| `settings.py` | 2 | comments on the OpenSpec CLI pin run through `npx` | Framework's own tooling, listed as such |
| `config.py` | 1 | the same, in the `openspec.command` comment | Framework's own tooling, listed as such |
| `timers.py` | 2 | `uv` is the command that starts a tick, so its availability is checked | Framework's own tooling, listed as such |

Related, and **not** matched by the list: the literal profile name `python-uv` is the default in `config.py` (two
fields), `pipeline/wiring.py` (two), `pipeline/gate.py` (two), `pipeline/check_failures.py`, `graph/nodes.py`
and `cli/pipeline.py`. A default profile is a configuration default and not a branch on an ecosystem, so it is
left; a follow-up may move it behind one named default in the profile registry.

### Two lists, with different rules

- **The allowlist** (`doctor.py`, `tracks/runner.py`) holds offenders to be removed. It may only shrink: a file
  whose matches are gone fails until it is taken off, and nothing is added. This is the shape of the timing
  guard in the test tree.
- **The framework's own tooling** (`openspec.py`, `serve/server.py`, `settings.py`, `config.py`, `timers.py`) is
  a second, fixed list, each entry with the reason it is not a consumer repository's toolchain: the framework
  is itself started with, tested with and shipped using tools, and calls the OpenSpec CLI. An entry is also
  checked for staleness. A reviewer can see a new entry in a diff and ask why.

The list of tokens is configuration of the check, in one place in the test helper, so a new ecosystem's manager
is one line. Matching is on the text of the file (comments included), so a comment cannot smuggle a name in.
The scan covers `.py` files; shipped data such as `recommendations/` (per-language seeds by design),
templates and skills is out of scope, and the unit files under `templates/` name the tool that starts a tick.

### The section

`AGENTS.md` gets "Framework code is language- and tool-independent" after "This repo never names an
installation". It says: the framework does not branch on a language, package manager, lock file name, test
runner or version-control host; that knowledge lives in toolchain profiles and the init detectors they
provide, in the forge layer for hosts, or in `abk.yaml`; a new behaviour is specified as configured argv lists,
path patterns and hooks; its tests use a second ecosystem's shape (a node-shaped fixture) beside the Python one;
and spec text uses a package manager or lock file name only as an example, never as the rule. The existing
Conventions line "Toolchain facts come from the profile" stays and points at it.

## Group 2: patterns and owned artifacts

### Patterns

- Relative to the repository root (the worktree root in a unit), `/` separators, `*` within one path component,
  `?` one character, `**` as a whole component any number of directories including none, `[...]` a class. A
  pattern naming a directory matches every file under it. `.git` is never matched. Leading `./` or `/` and
  `..` components are configuration errors, as a path outside the repository was never meaningful here.
- The result is a sorted list of files. The hash covers each pattern (as written), the sorted matches and each
  match's content. A pattern with no match contributes its text and `<missing>`, exactly as a missing literal
  name does today, so a literal path and a pattern that names one file hash the same way.
- `abk doctor` reports a pattern that matches nothing as it reports a missing input today.
- The base comparison (`_changed_from_base`) must work on patterns: a dependency input changed means the set of
  matched files differs between the base fork point and the worktree, or any matched file's git object id does.
  The base side is read with `git ls-tree` at the fork point, not by globbing a checkout.
- **A trap this exposes.** `**/package.json` also matches every manifest inside a dependency directory.
  Matching therefore excludes anything under a path matched by `artifacts` and anything git ignores for
  directories that are not artifacts is not consulted (ignore rules are the repository's, not the pipeline's).
  Without the exclusion, a sync that unpacks dependencies would change the hash it was triggered by, and the
  walk would visit the whole tree.
- A single matcher serves the hash, the base comparison, the dirty check's lock ownership and the artifact
  ownership, so the four cannot disagree.
- The generated-files derivation for sizing uses the final path component, as above.

### Artifacts

`environment.artifacts` is a list of path patterns, a sibling of `inputs` (not inside it: they are outputs of
the sync, and inputs are what it reads). Default empty. Rules, which are the lock rules without the
"committed when dependencies changed" exception:

1. Ignored by the dirty-worktree check, whether untracked or modified, and not listed as a leftover to an agent.
2. Never staged by the commit step, even when the unit changed a dependency input.
3. Never discarded by anything that resets or cleans the worktree on the pipeline's behalf.
4. **Not part of the hash.** The brief said the hash covers matched files' contents; applied to artifacts that
   is a bug, since a sync would change its own trigger and a dependency directory can hold hundreds of
   thousands of files. The hash covers the matched files of `dependencies`, `lock` and `other` only. This is
   recorded as a correction.
5. **A tracked file that matches an artifact pattern is not an artifact.** It is ordinary tracked work, and
   `abk doctor` warns that the pattern covers tracked files. (A repository that commits its vendored
   dependencies would otherwise lose changes silently.)

Where the ownership lives: the dirty check and commit step already take the lock paths as an argument resolved
from configuration; they take the artifact patterns the same way, and the matcher above decides.

Needs `environment-sync-leaves-no-leftovers` group 1 merged because it introduces that argument and the
rules on the lock paths that artifacts extend.

## Group 3: detection through profiles

- The profile protocol gains `detect_environment(root, *, framework) -> EnvironmentConfig | None`. A profile
  that cannot say returns None; a profile without the method counts as returning None, so a third-party profile
  keeps working.
- The Python profile receives the existing logic (manifest, lock, path sources, the check that loads the
  framework when `framework` is set) unchanged. A test pins the output of `abk init` for a Python repository,
  and for a Python repository with a path source.
- The registry gains an ordered walk. `abk init` asks the profile its repository detection already chose
  first, then the rest in registration order, and takes the first non-None. This keeps a mixed repository
  (a Python tool with a web front end) giving the Python result as today.
- `init/environment.py` keeps what is not ecosystem knowledge: the unrecognised draft with empty commands, and
  the lock names for the generated-file patterns.
- The node profile detects `package.json` and a lock file and proposes `sync`, `check`, inputs and artifacts
  (`node_modules`). Choice of manager: a `packageManager` field in `package.json` first, then the lock file
  (`package-lock.json` npm, `pnpm-lock.yaml` pnpm, `yarn.lock` yarn), then npm. Workspaces: a `workspaces`
  field becomes `dependencies` patterns (for example `package.json` plus `<workspace>/package.json`) and the
  lock pattern stays at the root.
- **UNVERIFIED, to be confirmed by the builder against each tool's documentation:** the exact argv lists. The
  starting proposals are `npm install` / `pnpm install` / `yarn install` for `sync` and a cheap listing
  command for `check` (`npm ls --depth=0`, `pnpm ls --depth 0`, `yarn --version` is not a health check and is
  not proposed). The frozen forms (`npm ci`, `pnpm install --frozen-lockfile`, `yarn install --immutable`)
  are deliberately not proposed: a frozen sync fails for exactly the unit that changed a dependency, the case
  `environment-sync-leaves-no-leftovers` rejected. Yarn's classic and modern lines differ in flags, and whether
  `npm ls` exits non-zero for a missing optional dependency is not established here.
- The node profile keeps refusing to build units (`ProfileUnsupported`); this change only lets init describe
  the environment, so a repository gets correct configuration before the profile can build in it.

### A draft never leaves the repository (added to group 3)

- **Found in use, and a correction to the first account of it.** The framework's own repository carries a
  checkout beside the installation as a manifest path source, and the installation's pipeline relies on that
  checkout's manifest: when it gained a dependency and the environment was not re-synced, three units failed.
  The installation listed that manifest and lock in `inputs`, which group 2 made a warning now and a
  configuration error next release (`path_patterns` and the `EnvironmentInputs` validator in `config.py`). At
  the merged commit the draft in `init/environment.py` no longer appends such paths (it skips a checkout whose
  path begins with `..`, with a comment that a pattern cannot leave the repository); so init does not write the
  refused config, it silently drops the drift signal. The fix is the same either way: detect drift by the
  check, not by hashing outside files.
- **The draft.** For a manifest with path sources the profile drafts `check` as
  `[sh, -c, "<lock freshness> && <environment freshness> && <import check>"]`, the import check last and only
  where the pipeline runs from this environment. For the Python profile the freshness commands are
  `uv lock --check` and `uv sync --check`. Verified on uv 0.11.32, offline, in a scratch project with a path
  source: `uv lock --check` re-resolves including the path source and exits 0 when current, and exits 1 with
  "needs to be updated" when the source gained a dependency; `uv sync --check` exits 0 with "Would make no
  changes" when in step, and exits 1 ("environment is outdated") when not. Exit codes beyond these are
  UNVERIFIED. Inputs keep only the repository's own manifest and lock. The wrapper is one argv because the
  configuration is argv lists and a shell wrapper is allowed; one check is enough because the tick already runs
  check, sync on failure, then check again, so a stale lock or environment fails the check, triggers the sync
  and passes afterwards. A comment in the draft says why. A manifest without path sources is drafted as before
  (pinned); another profile's draft is untouched.
- **The live installation** was changed by hand to this shape: its `check` is
  `[sh, -c, "uv lock --check && uv sync --check && uv run --no-sync python -c 'import agent_build_kit'"]` and
  its inputs are the planning repository's own manifest and lock only. The tick's `ensure` step confirmed it
  healthy.
- **The warning** from group 2 is merged text and is extended, not rewritten, to name the fix: use `check` to
  detect drift.

## Risks

- Pattern walks on large trees: matching reads the file list from git (`ls-files` plus untracked non-ignored)
  where possible and prunes artifact directories, so a hash is not a tree walk of `node_modules`.
- Moving detection changes the module `abk init` imports; the pinned-output test is the guard.
- The guard is textual and will flag a harmless mention; the cure is rewording, and the own-tooling list exists
  for the unavoidable cases.
