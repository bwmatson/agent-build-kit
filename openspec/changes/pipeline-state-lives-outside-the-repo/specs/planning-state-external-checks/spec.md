## ADDED Requirements

### Requirement: abk init writes no state into the repository when the state is outside it

In an in-repo installation whose state directory is outside the planning root, `abk init` and the scaffold SHALL NOT write `<state>/.gitkeep` or `<state>/units.json` and SHALL NOT add the state lines to the marked block of `.gitignore`; the lines for `.env`, `.last-runs/`, `*.pre-redact`, `abk.local.yaml` and `scrub.local` SHALL still be added. A separate planning repo SHALL be scaffolded as before. The orientation text SHALL name the resolved state and page paths.

#### Scenario: In-repo init

- **GIVEN** a repository with a listed repo and the default state setting
- **WHEN** `abk init` runs
- **THEN** no file is written under `runs/`, the `.gitignore` block has no `runs/` line, and it still ignores `.env` and `abk.local.yaml`

#### Scenario: Separate init

- **GIVEN** a new separate planning directory
- **WHEN** `abk init` runs
- **THEN** `runs/.gitkeep`, `runs/units.json` and the `runs/` ignore lines are written as before

### Requirement: abk doctor warns about state left in the repository

For an in-repo installation whose state directory is outside the root, `abk doctor` SHALL NOT warn about missing state ignore lines, and SHALL warn when git tracks files under the legacy `runs/`, naming the count, `docs/runbooks/move-state-out-of-the-repo.md` and that the state of this installation has not been moved. With no tracked file under `runs/` it SHALL report nothing for this. For an installation whose state is inside the root the check for the ignore lines SHALL be as before.

#### Scenario: Tracked legacy state

- **GIVEN** an in-repo installation with the default state and a tracked `runs/units.json`
- **WHEN** `abk doctor` runs
- **THEN** one warning names the count of tracked files under `runs/` and the runbook, and none is about ignore lines

#### Scenario: Moved

- **GIVEN** the same after `git rm -r runs/`
- **WHEN** `abk doctor` runs
- **THEN** there is no warning about `runs/`

#### Scenario: State inside the repository

- **GIVEN** `planning.state_dir: runs` in an in-repo installation whose `.gitignore` lacks the lines
- **WHEN** `abk doctor` runs
- **THEN** the missing-lines warning is given as before

### Requirement: abk planning split follows the state directory

`abk planning split` SHALL refuse, before writing anything and naming the directory, a plan whose source and destination resolve to the same state directory, saying to set `planning.home` in the destination's `abk.local.yaml`. For a side whose state directory is outside its root, the plan SHALL say that the state is outside the repository and not under git, and the uncommitted-changes report SHALL list only the specs directory. The copy and the removal SHALL read and write each side's `units.json` in that side's own state directory.

#### Scenario: Two plans in one repository

- **GIVEN** a source and a destination planned in one repository with no `planning.home` set
- **WHEN** `abk planning split` runs
- **THEN** it exits 1 naming the shared state directory and `planning.home`, and nothing is written

#### Scenario: Separate states

- **GIVEN** a destination with its own `planning.home`
- **WHEN** the split runs
- **THEN** the records are written to the destination's state directory and the source's are removed from its own

#### Scenario: Drift report

- **GIVEN** a source with an outside state directory and a modified spec file
- **WHEN** the plan is printed
- **THEN** only the spec file is listed as uncommitted and a line says the state is not under git

### Requirement: The documents and a runbook say where the state is

`docs/architecture.md` ("State on disk"), `docs/configuration.md` (the planning keys and "Where an installation's facts live"), `docs/tracks.md`, `docs/init.md`, the `abk-pipeline` and `abk-config` skills and the `planning-state-paths`, `planning-split` and `planning-worktree` specs SHALL say that an in-repo installation's state is in the planning home outside the repository and not committed, SHALL NOT say that `units.json` or `runs/` is committed there, and SHALL say that two hosts sharing the folder are unsupported. `docs/runbooks/move-state-out-of-the-repo.md` SHALL describe the move of an existing installation (stop the timers, `abk install-timers --no-enable`, copy the state, `git rm -r runs/` on the default branch, move the reports, reset the worktree, enable, check) and its rollback. `docs/runbooks/move-agent-build-kit-planning.md` SHALL no longer say that `runs/units.json` stays tracked. `CHANGELOG.md` SHALL have an entry under Unreleased.

#### Scenario: The documents are pinned

- **GIVEN** the documents
- **WHEN** the docs test reads them
- **THEN** none says `units.json` is committed, the architecture and configuration documents name `<planning home>/state`, and the changelog has the entry

#### Scenario: The runbook is complete

- **GIVEN** the runbook
- **WHEN** the docs test reads it
- **THEN** it holds the steps in order and a rollback section
