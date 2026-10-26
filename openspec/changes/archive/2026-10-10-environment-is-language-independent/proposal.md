# Proposal

## Why

The environment section (`sync` and `check` argv lists, `inputs` file lists) is language-neutral in design: the
pipeline runs the commands it is given and hashes the files it is told to. In practice four things tie it to one
ecosystem.

1. **Inputs are literal file paths.** The hash reads each listed path as one file. A repository whose manifests
   and lock files are many and move (npm workspaces, Maven modules, Gradle projects, Cargo workspaces, Python
   workspaces) cannot list them, and a new module silently falls outside the hash, so adding a dependency in it
   does not trigger a sync.
2. **Only lock files are pipeline-owned.** `environment-sync-leaves-no-leftovers` makes the lock paths the
   pipeline's own. Everything else a sync creates (dependency and build directories such as `node_modules`,
   `target`, `vendor`, a virtual environment, build output) is not. It relies on the repository's own ignore
   rules, so a repository that does not ignore them gets a unit held for the pipeline's own output, the same
   failure that change fixes for locks.
3. **`abk init` detects one ecosystem.** The environment draft knows only a Python project manager's manifest and
   lock. The node profile is declared but every method of it refuses, so init writes empty commands for such a
   repository, and a new ecosystem would mean another branch inside init.
4. **Nothing stops the framework naming an ecosystem.** The repository's conventions say toolchain facts come
   from the profile, but no check enforces it, so package manager and lock file names have drifted into the
   health checks, the track tool allowlist and comments.

## What Changes

- **A rule and a check.** The repository's `AGENTS.md` gains a section "Framework code is language- and
  tool-independent", and a test fails when framework source outside `profiles/` and `init/` names a package
  manager, a manifest or a lock file from a short configured list. Today's offenders are allowlisted; the
  allowlist may only shrink.
- **Inputs are patterns.** `environment.inputs.*` accept glob patterns relative to the repository, `**`
  included. A pattern that matches nothing is recorded as missing, as a missing file is.
- **Artifacts are owned.** A new `environment.artifacts` list names the paths a sync or check produces. They are
  ignored by the dirty-worktree check, never committed and never discarded, and are left out of the inputs
  matching.
- **Detection goes through profiles.** The toolchain profile gains an optional `detect_environment` hook. The
  Python profile's detection moves there with identical output, a node profile detects its manifest and lock
  file, and `abk init` asks each profile in the registry.
- **A draft never lists a path outside the repository.** Where the manifest has path sources the Python
  profile drafts `check` as a drift check (lock freshness, environment freshness, import check) and keeps only
  the repository's own manifest and lock as inputs; the deprecation warning names that remedy.
- **`limits.generated_files` needs no change to its default,** which is already empty; the lock names it once
  carried are derived from `environment.inputs.lock`. See the design.

## Impact

- Capability: `pipeline-environment` (added requirements).
- Code: the environment inputs hash and base comparison, the worktree dirty check and commit step (artifacts),
  `EnvironmentConfig`, the profile protocol and registry, the python and node profiles, `abk init`'s environment
  draft, `abk doctor`'s input check, one new repository test, `AGENTS.md`, and the configuration and init docs.
- Builds on `pipeline-environment` and `environment-sync-leaves-no-leftovers`: group 2 needs that change's
  group 1 merged.
