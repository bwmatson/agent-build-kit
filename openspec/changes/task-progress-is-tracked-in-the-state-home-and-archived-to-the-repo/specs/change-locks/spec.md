## ADDED Requirements

### Requirement: Locks on a change's files are kept outside the repository

A lock taken for a file of a change SHALL be at `<local dir>/locks/changes/<change>/<name>.lock`, from one helper, `change_lock(inst, change, name)`, and no lock file SHALL be created beside a file under the changes directory. The writers of the repository `tasks.md` (`add_needs`, `abk tags --fix`) SHALL take the lock `tasks.md`, the tick of the copy the lock `progress`, and the follow-ups writer the lock `follow-ups.md`; the first two SHALL be taken in the order `progress`, then `tasks.md`. The local directory SHALL be `planning.local_dir` when the installation has that setting, else `<planning home>/local`, else, in a separate planning repo, `<state dir>/locks`.

#### Scenario: A tick leaves no lock in the change

- **GIVEN** a change directory in the pipeline worktree
- **WHEN** a unit is ticked, a follow-up recorded, a `Needs:` line added and `abk tags --fix` run on it
- **THEN** no file named `*.lock` exists under the changes directory, and the lock files are under `<local dir>/locks/changes/<change>/`

#### Scenario: Two writers still exclude each other

- **GIVEN** a thread holding `change_lock(inst, change, "tasks.md")`
- **WHEN** `add_needs` runs for the same change
- **THEN** it waits until the first is done, and a lock of another change is not held up

#### Scenario: A separate planning repo

- **GIVEN** an installation with no planning home
- **WHEN** a change lock is taken
- **THEN** it is under `<state dir>/locks/changes/<change>/`

### Requirement: Stray lock files in the changes directory are reported and removed

`abk doctor` SHALL warn when a file named `*.md.lock` exists under the changes directory, naming the count and `abk doctor --fix`. `abk doctor --fix` SHALL delete each such file that git does not track and that no process holds, leave the others, name each tracked one with `git rm`, and change nothing else. The planning `.gitignore` block SHALL contain `*.md.lock`, so that a lock made by another tool is not staged.

#### Scenario: Old locks are removed

- **GIVEN** untracked `tasks.md.lock` and `follow-ups.md.lock` in a change directory
- **WHEN** `abk doctor --fix` runs
- **THEN** both are deleted and the doctor then reports no warning for them

#### Scenario: A held or tracked lock is kept

- **GIVEN** one lock a process holds and one that git tracks
- **WHEN** `abk doctor --fix` runs
- **THEN** neither is deleted, the held one is reported as in use, and the tracked one is named with the `git rm` step

#### Scenario: Nothing to fix

- **GIVEN** no such file
- **WHEN** `abk doctor` runs
- **THEN** there is no lock check line, and `--fix` changes nothing

#### Scenario: The ignore block

- **GIVEN** a new planning repo made by `abk init`
- **WHEN** its `.gitignore` is read
- **THEN** the abk block holds `*.md.lock` and, for the state directory, the tracking folder
