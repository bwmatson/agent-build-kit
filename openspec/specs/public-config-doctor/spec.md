# public-config-doctor Specification

## Purpose
TBD - created by archiving change planning-content-follows-the-public-rule. Update Purpose after archive.

## Requirements

### Requirement: Doctor warns when a tracked abk.yaml carries facts a public repo must not

`abk doctor` SHALL add a check named `public content`. When the planning root is a git repository and `abk.yaml` is tracked by it, the
check SHALL read the committed file's own text (parsed directly, not through the loader) and SHALL warn once for each finding: a `repos.<name>.path` that resolves
outside the repository's top level; a string value containing a home-directory path; a repo whose forge account differs, case-insensitively,
from the account of the repository's own `origin` URL (a repo whose path is `.` exempt). It SHALL make no network call, SHALL warn and never
fail, and SHALL print the key path and the fix and never the value. When the file is untracked, or the root is not a repository, the check SHALL be `ok`.

#### Scenario: A path outside the checkout

- **GIVEN** a tracked abk.yaml with a repo whose path is a sibling directory
- **WHEN** `abk doctor` runs
- **THEN** a warning names `repos.<name>.path` and says to keep the value in the ignored `.env` or `abk.local.yaml`, or to remove the entry

#### Scenario: A home path in a value

- **GIVEN** a tracked abk.yaml with a provider file under the home directory
- **WHEN** `abk doctor` runs
- **THEN** a warning names the key path and the value is not printed

#### Scenario: Another owner's slug

- **GIVEN** a planning repo whose origin is owned by `example` and a repo entry owned by another account
- **WHEN** `abk doctor` runs
- **THEN** a warning names the entry and the accounts are not printed in full beyond the entry's key

#### Scenario: The checkout's own entry

- **GIVEN** a repo entry with path `.` and the origin's own owner
- **WHEN** `abk doctor` runs
- **THEN** the check is `ok`

#### Scenario: Not tracked

- **GIVEN** an abk.yaml that git ignores
- **WHEN** `abk doctor` runs
- **THEN** the check is `ok` and says the file is not tracked

#### Scenario: No origin

- **GIVEN** a repository with no remote
- **WHEN** `abk doctor` runs
- **THEN** the owner finding is skipped and the other findings still run

### Requirement: Doctor warns when the overlay, the local list or a redaction copy could be committed

The check SHALL also warn when `abk.local.yaml` or `scrub.local` exists and is tracked or not ignored by git, and when a `*.pre-redact`
file exists that git does not ignore, each time naming the file and the line to add to the ignore file.

#### Scenario: An overlay not ignored

- **GIVEN** an `abk.local.yaml` and an ignore file without it
- **WHEN** `abk doctor` runs
- **THEN** a warning names the file and the line to add

#### Scenario: A tracked overlay

- **GIVEN** an `abk.local.yaml` that was committed
- **WHEN** `abk doctor` runs
- **THEN** a warning says it is tracked and to remove it from the index

#### Scenario: An unignored copy

- **GIVEN** a `units.json.pre-redact` that git does not ignore
- **WHEN** `abk doctor` runs
- **THEN** a warning names it

#### Scenario: All ignored

- **GIVEN** the overlay, the list and the copy all ignored
- **WHEN** `abk doctor` runs
- **THEN** the check is `ok`

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
