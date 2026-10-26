## ADDED Requirements

### Requirement: Doctor classifies the machine settings of a committed abk.yaml from one table and names the migration

`abk doctor` SHALL add a check named `machine keys`. When the planning root is a git repository and `abk.yaml` is tracked by it, the check SHALL read the committed file alone (parsed directly,
not through the loader; the overlay is not read) and classify its settings from the one table of machine settings that `abk config --migrate` also reads: a **machine choice** gets a warning, a
**fine-to-commit default** gets a note. The machine choices are `repos.<name>.account`, `repos.<name>.path` when it resolves outside the repository's top level, `repos.<name>.deploy.ssh_key`,
`planning.worktree_root`, `project_limits`, `runtimes.<name>.accounts`, an absolute program path in `runtimes.<name>.command` or `policy_fix`, `tests.e2e_available` (also under a repo's `tests`),
and, in a `verify.env.<NAME>` entry, the `file`, `value` or `argv` that holds a home-directory path. The defaults are `runtimes.<name>.limits`, `tests.e2e_schedule` when off, and a split's `hold`.
Each message SHALL name the key path and never the value. A warning SHALL read `<key> in abk.yaml <reason>: a machine choice` with the fix ``move it to abk.local.yaml with `abk config --migrate` ``; a note
SHALL read `<key> in abk.yaml: <reason>` with the fix ``fine to commit; move it to abk.local.yaml to differ (`abk config --migrate --include-defaults` moves it) ``. The check SHALL make no network call,
SHALL warn and never fail, and SHALL say nothing when the file is untracked or the root is not a repository, or about `runtimes.<name>.models` or the same keys in `abk.local.yaml`.

#### Scenario: A project_limits block

- **GIVEN** a tracked abk.yaml with a `project_limits` block
- **WHEN** `abk doctor` runs
- **THEN** a warning names `project_limits`, says it is a machine choice, and its fix names `abk config --migrate`

#### Scenario: The documented path settings

- **GIVEN** a tracked abk.yaml with `repos.app.path: ../app`, `repos.app.deploy.ssh_key: ~/.ssh/deploy`, `planning.worktree_root: ~/work/trees` and a `verify.env.TOKEN.file: ~/.config/app/.env`
- **WHEN** `abk doctor` runs
- **THEN** a warning names each of `repos.app.path`, `repos.app.deploy.ssh_key`, `planning.worktree_root` and `verify.env.TOKEN.file`, and no value is printed

#### Scenario: A path inside the checkout

- **GIVEN** a repo entry with path `.`
- **WHEN** `abk doctor` runs
- **THEN** the `machine keys` check names no path for it

#### Scenario: A default is a note

- **GIVEN** a tracked `runtimes.claude_code.limits`
- **WHEN** `abk doctor` runs
- **THEN** a note names the key, says it is fine to commit, and names `abk config --migrate --include-defaults`

#### Scenario: The migration clears the warnings

- **GIVEN** the files left by `abk config --migrate --include-defaults`
- **WHEN** `abk doctor` runs
- **THEN** the `machine keys` check names nothing

#### Scenario: One table

- **WHEN** a key is added to the table of machine settings
- **THEN** both the doctor and the migration act on it, and neither names a key of its own
