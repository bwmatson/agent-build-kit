## ADDED Requirements

### Requirement: The commit hooks leave the state directory alone

The repo's commit-hook configuration SHALL exclude the state directory from every hook that edits or size-checks files, and SHALL still run the YAML linter in strict mode on `abk.yaml`.

#### Scenario: The unit store

- **GIVEN** a `runs/units.json` of 1.4 MB and a run log with trailing whitespace and no final newline
- **WHEN** the hooks run over a commit holding them
- **THEN** none rejects or rewrites them

#### Scenario: abk.yaml

- **GIVEN** an `abk.yaml` with a lint error
- **WHEN** the hooks run over it
- **THEN** the strict YAML check fails

### Requirement: A spec-and-state commit does not run the whole suite

The repo's CI SHALL decide from the changed paths whether anything outside the planning paths (the specs directory, the state directory and the two generated pages) changed. The test and integration jobs SHALL run only when
it did, the hook job SHALL always run, and a skipped job SHALL leave the workflow's required checks satisfied.

#### Scenario: A tick's own commit

- **GIVEN** a push whose changed files are all under `openspec/`, `runs/` or the two pages
- **WHEN** CI is evaluated
- **THEN** the hook job runs and the test and integration jobs are skipped

#### Scenario: A code change

- **GIVEN** a pull request that also changes a source file
- **WHEN** CI is evaluated
- **THEN** every job runs

#### Scenario: abk.yaml alone

- **GIVEN** a change that only edits `abk.yaml`
- **WHEN** CI is evaluated
- **THEN** the hook job runs and the others are skipped
