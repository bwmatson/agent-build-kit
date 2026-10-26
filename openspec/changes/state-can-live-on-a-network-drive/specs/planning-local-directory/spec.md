## ADDED Requirements

### Requirement: Machine-local files live in a local directory

The installation SHALL have a local directory, `planning.local_dir`, for every file whose meaning is tied to the processes of this machine: the checkpointer database (`unit-graphs.sqlite` and its `-wal` and `-shm`), the branch and repo locks (`locks/`), the change locks, the leases (`leases/`), the e2e-test lock and `environment.lock`. The state directory SHALL hold no such file. The setting SHALL be read from, strongest first, `ABK_LOCAL_DIR`, the ignored `abk.local.yaml`, then `abk.yaml`; it SHALL be an absolute or `~` path, and a relative value SHALL be refused naming the setting. Unset, it SHALL be `<planning home>/local` when the installation has a planning home, and the state directory itself for a separate planning repo whose state stays in `runs/`.

#### Scenario: The default keeps local files beside the state, not in it

- **GIVEN** an in-repo installation with the default planning home and no `planning.local_dir`
- **WHEN** the installation is loaded
- **THEN** `local_dir` is `<planning home>/local`, `state_dir` is `<planning home>/state`, and the checkpointer, `locks/`, `leases/`, the e2e-test lock and `environment.lock` resolve under `local_dir` and none under `state_dir`

#### Scenario: Moving only the state to a share leaves the local files local

- **GIVEN** `planning.state_dir` set to a path on a share and `planning.local_dir` unset
- **WHEN** the installation is loaded
- **THEN** `local_dir` is still under the planning home and the share holds none of the local files

#### Scenario: The environment overrides the files

- **GIVEN** `ABK_LOCAL_DIR` set and a different `planning.local_dir` in `abk.local.yaml`
- **WHEN** the installation is loaded
- **THEN** `local_dir` is the environment's

#### Scenario: A relative path is refused

- **GIVEN** `planning.local_dir: tmp/local`
- **WHEN** the installation is loaded
- **THEN** the load fails naming `planning.local_dir` and saying the path must be absolute or start with `~`

#### Scenario: A separate planning repo is unchanged

- **GIVEN** a separate planning repo with state in `runs/` and no `planning.local_dir`
- **WHEN** the installation is loaded
- **THEN** `local_dir` is the state directory and every local file is where it was

### Requirement: An existing checkpointer database is carried once

When the checkpointer opens its database in a local directory that differs from the state directory and holds none, and the state directory holds `unit-graphs.sqlite`, the pipeline SHALL copy that database to the local directory through SQLite's backup interface before opening, SHALL leave the old file in place, and SHALL not copy again once the local one exists. Old `locks/`, `leases/`, `e2e.lock` and `environment.lock` under the state directory SHALL be ignored. `abk doctor` SHALL warn, naming each, for every one that remains under the state directory while the local directory differs.

#### Scenario: A thread resumes after the move

- **GIVEN** a state directory holding a database with a unit's thread and no database in the local directory
- **WHEN** the checkpointer is opened
- **THEN** the thread is readable from the local copy, the old file is unchanged, and a second open copies nothing

#### Scenario: Old locks are ignored and reported

- **GIVEN** a state directory still holding `locks/repo-app.lock` and a lease file
- **WHEN** the pipeline takes the repo lock and `abk doctor` runs
- **THEN** the lock taken is under the local directory, and the doctor warns naming the old files and saying to delete them

### Requirement: The doctor checks the local directory

`abk doctor` SHALL fail when `local_dir` is on a network or other non-local filesystem, naming the path, the filesystem type and the fix (set `planning.local_dir` or `ABK_LOCAL_DIR` to a local disk), because the checkpointer database and the host locks are unsafe there.

#### Scenario: A local directory on a share fails

- **GIVEN** a `local_dir` whose mount type is `cifs`
- **WHEN** `abk doctor` runs
- **THEN** the `local dir` check fails naming the type and the setting to change

#### Scenario: A local directory on local disk passes

- **GIVEN** a `local_dir` on `ext4`
- **WHEN** `abk doctor` runs
- **THEN** the `local dir` check is ok
