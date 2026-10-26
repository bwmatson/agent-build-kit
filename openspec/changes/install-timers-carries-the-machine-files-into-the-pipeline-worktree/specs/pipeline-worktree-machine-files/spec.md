## ADDED Requirements

### Requirement: The machine files have one list

The files that make an installation this machine's SHALL be listed once: `.env`, `abk.local.yaml` and `scrub.local`. The carrying into a pipeline worktree, `abk doctor`'s check that local files are ignored and `abk config --migrate`'s `.gitignore` step SHALL read that list and keep no literal names of their own. The redaction copies (`*.pre-redact`) SHALL NOT be in it.

#### Scenario: One list serves the three readers

- **GIVEN** the list
- **WHEN** the doctor's public-content check, the migration's ignore step and the carrying run
- **THEN** each acts on names from the list, and no other source file names `scrub.local` or `abk.local.yaml` as a literal for these purposes

### Requirement: install-timers carries the machine files into the pipeline worktree

When the planning root is also a code repo, `abk install-timers` SHALL link each machine file the working copy has into the pipeline worktree, whether it is run from the working copy or from the worktree, before the units are written. The link SHALL be a symbolic link with an absolute target in the working copy, and the files SHALL stay untracked: a file git would not ignore in the worktree SHALL be refused, naming the file and the step that ignores it. A file the working copy does not have SHALL be skipped without error. A path in the worktree that is a regular file with different bytes, or a link to another existing file, SHALL be refused naming it and SHALL NOT be changed. A path that is a regular file with the same bytes, or a link to the same file, SHALL be left as it is and reported `unchanged`; a dangling link SHALL be repointed. Every refusal SHALL be found before any link is made, SHALL print one line on standard error naming the file, SHALL exit 1 and SHALL leave the units unwritten. `--dry-run` SHALL print `would link` for each link it would make and write nothing. The sync of the worktree SHALL NOT remove a link.

#### Scenario: The files are linked

- **GIVEN** a working copy with `abk.local.yaml`, `.env` and `scrub.local`, all ignored
- **WHEN** `abk install-timers` makes the worktree
- **THEN** the worktree holds a symbolic link for each, resolving to the working copy's file, `git status` in the worktree is clean, and the output has a `linked` line for each

#### Scenario: The worktree loads the machine configuration

- **GIVEN** a working copy whose `abk.local.yaml` sets `planning.worktree_root`
- **WHEN** the installation is loaded from the worktree after the install
- **THEN** `worktree_root` is that path, and a later edit to the working copy's file is read at once

#### Scenario: A file the working copy lacks is skipped

- **GIVEN** a working copy with only `.env`
- **WHEN** `abk install-timers` runs
- **THEN** one link is made, nothing is said about the other two, and the exit is 0

#### Scenario: A re-run changes nothing

- **GIVEN** an install that linked the files
- **WHEN** `abk install-timers` runs again
- **THEN** each line is `unchanged`, no link is touched, and a link that dangles is repointed and reported

#### Scenario: A different file is never overwritten

- **GIVEN** a worktree holding a regular `abk.local.yaml` that differs from the working copy's
- **WHEN** `abk install-timers` runs
- **THEN** it exits 1 naming that file, the file is byte for byte as before, no other link was made and no unit was written

#### Scenario: A file git would show is refused

- **GIVEN** a worktree whose `.gitignore` lacks `scrub.local`
- **WHEN** `abk install-timers` runs with a `scrub.local` in the working copy
- **THEN** it exits 1 naming `scrub.local` and the line to add, and nothing is linked

#### Scenario: Run from the worktree

- **GIVEN** the worktree is the installation in force
- **WHEN** `abk install-timers` runs there
- **THEN** the files are linked from the main working tree, and when that cannot be found a note says nothing was carried

#### Scenario: The sync keeps the links

- **GIVEN** the linked files and a new commit on the default branch
- **WHEN** the worktree is synced
- **THEN** it moves to the tip and every link is still there

### Requirement: abk doctor reports a machine file the worktree lacks

For an installation live in a pipeline worktree, `abk doctor`, run from the working copy or the worktree, SHALL have a `machine files` check. For each machine file the working copy has, the check SHALL pass when the worktree's path resolves to the same file or holds the same bytes, and SHALL FAIL when it is missing, dangling or different, naming the file and giving `abk install-timers` as the repair. A file the working copy lacks SHALL NOT be reported. When the working copy has none of the files, the check SHALL be a warning saying the pipeline runs on defaults and naming what to create. A separate planning repo, and an in-repo installation with no live worktree, SHALL have no such check.

#### Scenario: A missing file fails

- **GIVEN** a live worktree and a working copy with `abk.local.yaml`, with no link made
- **WHEN** `abk doctor` runs from either
- **THEN** the check is FAIL, names `abk.local.yaml` and `abk install-timers`

#### Scenario: A carried set passes

- **GIVEN** the files linked by the install
- **WHEN** `abk doctor` runs
- **THEN** the check is ok

#### Scenario: A different file fails

- **GIVEN** a regular `.env` in the worktree whose bytes differ from the working copy's
- **WHEN** `abk doctor` runs
- **THEN** the check is FAIL and names `.env`

#### Scenario: A machine with none of the files warns

- **GIVEN** a second clone with a live worktree and none of the three files
- **WHEN** `abk doctor` runs
- **THEN** the check is a warning that names `abk.local.yaml`, `.env` and `scrub.local`, and no check fails for them

#### Scenario: Not in a worktree

- **GIVEN** a separate planning repo, or an in-repo installation with no live worktree
- **WHEN** `abk doctor` runs
- **THEN** there is no `machine files` check

### Requirement: The documents say the files stay untracked and are carried

`docs/init.md`, `docs/configuration.md` ("Where an installation's facts live" and the roles paragraph) and the runbook for moving the kit's planning SHALL say that the machine files stay untracked and that `abk install-timers` carries them into the pipeline worktree, and that a new machine creates them in its working copy first. `CHANGELOG.md` SHALL have an entry under Unreleased.

#### Scenario: The documents are pinned

- **GIVEN** the documents
- **WHEN** the docs test reads them
- **THEN** each says the files stay untracked and that `install-timers` carries them, and the changelog has the entry
