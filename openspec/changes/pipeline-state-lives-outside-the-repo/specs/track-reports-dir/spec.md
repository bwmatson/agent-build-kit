## ADDED Requirements

### Requirement: The tracks keep their reports in a reports directory

`planning.reports_dir` SHALL name where the tracks' run logs (`<run id>-<repo>-<track>.md`), `tracked-issues.md` and `rejected-changes/` live, relative to the planning root, and SHALL be refused when it is outside the root. When unset it SHALL be the state directory if that is inside the root, and `docs/reports` if the state directory is outside it. Every track path that was derived from the state directory (the run log, the lookup of a prior run for `--focus`, the dirty-file listing, the commit pathspec, the message that names where logs go, and the rejected-change directory) SHALL be derived from the reports directory, and none SHALL fail when the state directory is outside the root.

#### Scenario: Outside state, default reports

- **GIVEN** an in-repo installation whose state directory is outside the repository
- **WHEN** a track phase finishes
- **THEN** its run log is `docs/reports/<run id>-<repo>-<track>.md` and no error is raised about a path outside the root

#### Scenario: Old layout unchanged

- **GIVEN** a separate planning repo with the state directory `runs`
- **WHEN** a track phase finishes
- **THEN** the run log is `runs/<run id>-<repo>-<track>.md`

#### Scenario: A reports directory outside the repo

- **GIVEN** `planning.reports_dir` naming a path outside the root
- **WHEN** the installation is loaded
- **THEN** it fails with a configuration error naming `planning.reports_dir`

#### Scenario: A rejected change

- **GIVEN** a propose phase whose change does not validate and an outside state directory
- **WHEN** the runner sets it aside
- **THEN** it is kept under `docs/reports/rejected-changes/<change>` and the note names that path

#### Scenario: Focus finds a prior run

- **GIVEN** a prior health run log in the reports directory
- **WHEN** a propose phase runs with `--focus health`
- **THEN** it resolves to that log

### Requirement: The reports are committed as before, by path

`commit_bookkeeping` SHALL commit and push only the Markdown under the reports directory (and the changes the phase wrote), by that pathspec, whether `planning.publish` is `direct` or `branch`, with the same retry after a rejected push. Files of the state directory SHALL NOT be committed.

#### Scenario: Direct publish

- **GIVEN** a pipeline worktree with `planning.publish: direct`, an outside state directory and a new run log under `docs/reports`
- **WHEN** the phase's bookkeeping is committed
- **THEN** one commit holds the run log and `tracked-issues.md` and is pushed to the default branch

#### Scenario: Branch publish

- **GIVEN** `planning.publish: branch`
- **WHEN** the bookkeeping is committed
- **THEN** it goes to a `planning/...` branch as before, holding only files under `docs/reports`

#### Scenario: State files are left out

- **GIVEN** a Markdown file in the state directory
- **WHEN** the bookkeeping is committed
- **THEN** it is not part of the commit

### Requirement: A track agent may write the reports and nothing in the state

The write fence SHALL grant a track run `*.md` writes under the reports directory, as it granted them under the state directory, and SHALL NOT grant writes under an outside state directory. The prompts SHALL name the reports directory with `__REPORTS_DIR__`; `__STATE_DIR__` SHALL still be substituted, with the reports directory. The hook flag SHALL be `--planning-reports-dir`, and the earlier `--planning-state-dir` SHALL be read as the same.

#### Scenario: A run log write

- **GIVEN** a track run with reports directory `docs/reports`
- **WHEN** its agent writes `docs/reports/<run id>-app-health.md`
- **THEN** the write is allowed

#### Scenario: A write to the state

- **GIVEN** the same with the state outside the repository
- **WHEN** its agent writes a file in the state directory
- **THEN** the write is denied as a path outside the grant

#### Scenario: The old token

- **GIVEN** a prompt in a user's prompts directory containing `__STATE_DIR__`
- **WHEN** it is rendered
- **THEN** the token is the reports directory

#### Scenario: Prompts read the reports

- **GIVEN** the packaged prompts
- **WHEN** they are rendered for a project
- **THEN** each names the prior run log and `tracked-issues.md` under the reports directory and `read_status` reads the health log there
