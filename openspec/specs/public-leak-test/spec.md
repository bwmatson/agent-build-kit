# public-leak-test Specification

## Purpose
TBD - created by archiving change planning-content-follows-the-public-rule. Update Purpose after archive.

## Requirements

### Requirement: The structural leak test also reads planning content

The framework's term-free leak test SHALL also scan `openspec/`, the committed `abk.yaml` and the tracked unit store file (when present)
with its home-path, slug, anecdote and product-directory checks, and SHALL report each hit as a path, a line number and a clipped line.
It SHALL NOT scan ignored state (`runs/` apart from the unit store, logs, ledgers).

#### Scenario: A home path in a spec

- **GIVEN** a file under `openspec/` containing a home-directory path
- **WHEN** the test runs
- **THEN** it fails naming the file and line

#### Scenario: A foreign slug in the config

- **GIVEN** an `abk.yaml` containing a code-host URL of an owner that is not a fixture
- **WHEN** the test runs
- **THEN** it fails naming the file and line

#### Scenario: Ignored state is not read

- **GIVEN** a home path in a run log under the state directory
- **WHEN** the test runs
- **THEN** it does not fail for it

#### Scenario: No planning content

- **GIVEN** a checkout with no `openspec/`, no `abk.yaml` and no store file
- **WHEN** the test runs
- **THEN** it passes and does not fail for the missing paths

### Requirement: A tracked abk.yaml names no path outside its checkout

The test SHALL parse the committed `abk.yaml` and SHALL fail for a `repos.<name>.path` that is absolute or begins with `~` and is not
inside the checkout, or that climbs out with `..`, naming the repo key and not printing the value.

#### Scenario: A sibling checkout

- **GIVEN** a repo entry whose path is `../other`
- **WHEN** the test runs
- **THEN** it fails naming the entry

#### Scenario: The checkout itself

- **GIVEN** a repo entry whose path is `.`
- **WHEN** the test runs
- **THEN** it passes

#### Scenario: A path inside the checkout

- **GIVEN** a repo entry whose path is `vendor/sub`
- **WHEN** the test runs
- **THEN** it passes

### Requirement: An overlay that could be committed is a leak, and is read

The test SHALL scan the committed `abk.yaml` as before. It SHALL also check `abk.local.yaml` beside it when the file exists: when git
tracks it, or does not ignore it (`git check-ignore`), the test SHALL fail naming the file, and SHALL scan its text with the same home-path,
slug and anecdote checks and its `repos.<name>.path` entries with the same outside-the-checkout rule. An overlay that exists, is ignored and
is untracked SHALL NOT be read, and neither SHALL a missing one. Outside a git repository the file SHALL be treated as not ignored.

#### Scenario: A tracked overlay

- **GIVEN** an `abk.local.yaml` committed to the repository
- **WHEN** the test runs
- **THEN** it fails naming the file as tracked, and a home path inside it is reported with its line

#### Scenario: An overlay not ignored

- **GIVEN** an untracked `abk.local.yaml` that no ignore rule covers
- **WHEN** the test runs
- **THEN** it fails naming the file as not ignored

#### Scenario: An ignored overlay is not read

- **GIVEN** an ignored, untracked `abk.local.yaml` holding a home path and a sibling repo path
- **WHEN** the test runs
- **THEN** it passes

#### Scenario: No overlay

- **GIVEN** no `abk.local.yaml`
- **WHEN** the test runs
- **THEN** it passes
