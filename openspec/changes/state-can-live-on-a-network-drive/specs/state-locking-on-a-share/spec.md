## ADDED Requirements

### Requirement: A state lock waits a bounded time

`file_lock` SHALL wait for the lock at most `ABK_LOCK_WAIT_SECONDS` seconds (default 120) and then raise `LockTimeout`, a `TimeoutError`, whose message names the file, the seconds waited, the setting and the filesystem type of the file. It SHALL change nothing on a timeout: the lock file, the file it guards and every record stay as they were. A lock free within the wait SHALL be taken as before, and `try_file_lock` and the e2e-test lock's own wait SHALL be unchanged.

#### Scenario: A held lock times out

- **GIVEN** a lock held by another handle and `ABK_LOCK_WAIT_SECONDS` of 1
- **WHEN** `file_lock` is asked for the same file
- **THEN** it raises `LockTimeout` after about one second naming the file and the setting, and the holder still holds the lock

#### Scenario: A lock freed in time is taken

- **GIVEN** a lock released 0.2 seconds after another handle asked for it
- **WHEN** the wait is 5 seconds
- **THEN** the second handle takes it and no error is raised

### Requirement: An atomic write is named per host and synced

`atomic_write_text` and `atomic_write_bytes` SHALL write a temporary file named `<name>.<host>.<pid>.tmp`, fsync it before `os.replace`, fsync the directory afterwards ignoring a refusal, and remove the temporary and keep the old file when anything raises. A rename refused with `PermissionError` or `EBUSY` SHALL be retried up to five times with a doubling pause from 0.1 seconds before the error is raised.

#### Scenario: The temporary names the host and the file is synced first

- **GIVEN** a host named `box` and a write of `units.json`
- **WHEN** the write runs with `os.fsync` and `os.replace` recorded
- **THEN** the temporary was `units.json.box.<pid>.tmp`, it was fsynced before the replace, and no temporary remains

#### Scenario: A busy rename is retried

- **GIVEN** a replace that raises `PermissionError` twice and then succeeds
- **WHEN** the write runs
- **THEN** the file holds the new text and the old one was not removed between attempts

#### Scenario: A persistent refusal raises and keeps the old file

- **GIVEN** a replace that always raises `EBUSY`
- **WHEN** the write runs
- **THEN** after five retries the error is raised, the old file is unchanged and no temporary remains

### Requirement: The lock probe refuses a state directory whose locks do not exclude

The pipeline SHALL probe a directory by holding `flock` on a file in it and asking a second process to take the same lock without waiting. The probe SHALL pass only when the second process is refused and takes the lock once the first is released. It SHALL fail when the second process is granted the lock, when it gets an error (no lock support), or when it does not answer within ten seconds, and SHALL remove its file in every case. `abk doctor` SHALL run it on the state directory and report a failure with the mount type, what the probe saw and the fix. The tick SHALL run it at its start only when the state directory is not on a local filesystem, SHALL cache the result in the local directory for 24 hours keyed by the mount's source, type and options, and SHALL on a failure print the doctor's detail, write nothing and exit 1 before the planning sync. A state directory on a local filesystem SHALL cost the tick nothing. No setting SHALL run the pipeline on a state directory the probe refused.

#### Scenario: Working locks pass

- **GIVEN** a directory where a second process is refused while the first holds the lock
- **WHEN** the probe runs
- **THEN** it passes and leaves no probe file

#### Scenario: Locks that exclude nothing fail

- **GIVEN** a probe whose second process reports it was granted the lock
- **WHEN** the probe runs on a `cifs` mount
- **THEN** it fails, the detail names `cifs` and says two processes both held the lock, and the fix names mounting with `nobrl` or moving `planning.state_dir` to a local disk

#### Scenario: A filesystem without locks fails

- **GIVEN** a probe whose second process reports `ENOLCK`
- **WHEN** the probe runs
- **THEN** it fails naming the error and the mount type

#### Scenario: A silent mount times out

- **GIVEN** a probe whose second process does not answer in ten seconds
- **WHEN** the probe runs
- **THEN** it fails saying it timed out, and the first process's lock is released

#### Scenario: The tick refuses on a share that failed

- **GIVEN** a state directory on an `nfs4` mount and a failed probe
- **WHEN** `abk tick` starts
- **THEN** it prints the detail, exits 1, and has written nothing to the state directory or synced the planning worktree

#### Scenario: The tick trusts a cached pass

- **GIVEN** a pass cached an hour ago for the same mount source, type and options
- **WHEN** `abk tick` starts
- **THEN** no probe process is started

#### Scenario: A changed mount is probed again

- **GIVEN** a cached pass for `nolock` and a mount now without it
- **WHEN** `abk tick` starts
- **THEN** the probe runs

#### Scenario: A local state costs nothing

- **GIVEN** a state directory on `ext4`
- **WHEN** `abk tick` starts
- **THEN** no probe runs and no cache is written

### Requirement: The doctor reports where the state is

`abk doctor` SHALL report the state directory's mount: an info line naming the filesystem type and source and saying that one pipeline host is supported when it is not local; nothing when it is. It SHALL warn on a `hard`-mounted share, naming the option.

#### Scenario: A share is named

- **GIVEN** a state directory on `nfs4` from `files:/export`
- **WHEN** `abk doctor` runs
- **THEN** the `state mount` line names `nfs4`, `files:/export` and one pipeline host
