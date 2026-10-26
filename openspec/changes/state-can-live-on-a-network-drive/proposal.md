# Proposal

## Why

The pipeline's state directory is meant to be application state a person can move (`pipeline-state-lives-outside-the-repo` makes it a per-repository planning home with `planning.state_dir` overridable), and the first thing a person moves it to is a share, so the state survives the machine and can be browsed from another one. Today that would be wrong in ways nobody sees:

- **One directory holds both kinds of file.** `unit-graphs.sqlite` is opened in WAL mode (`graph/checkpointer.py:37-44`), which needs shared memory and is unsafe on NFS, SMB and WSL's drvfs, and sits in the state directory (`graph/checkpointer.py:32-34`). The branch locks (`pipeline/workspaces.py:50-51, 83-121`), the repo locks (`cli/pipeline.py:5322-5326`), the leases (`pipeline/lease.py:20-22`), `e2e.lock` (`installation.py:99-101`) and `environment.lock` (`pipeline/environment.py:349`) are all under it too, and every one of them is a claim about processes on this machine.
- **`flock` can fail silently.** `file_lock` takes `fcntl.flock(handle, LOCK_EX)` (`pipeline/file_lock.py:25-33`). On a mount where locks are not supported or are not honoured, the call may succeed and exclude nothing, and the unit store's read-modify-write (`pipeline/unit_store.py:669`) then loses updates with no error. The same call has no timeout, so a mount that stops answering hangs the tick holding its place for ever.
- **Writes assume a local rename.** `atomic_write_text` writes `<name>.<pid>.tmp` and renames (`pipeline/file_lock.py:67-75`): two hosts' processes can share a pid, nothing is synced before the rename (a power loss can leave a zero-length file under the final name), and a rename over a file another client has open fails on SMB.
- **Holders are judged by local process tables.** A lease is live when `/proc/<pid>/stat` agrees (`pipeline/lease.py:25-33, 76-78`), a branch lock when `os.kill(pid, 0)` finds the pid (`pipeline/workspaces.py:54-63, 101-107`), the e2e lock record likewise (`pipeline/e2e.py:341, 353, 433`). Read on another host those answer "dead", and the record is stolen.

## What Changes

- **`planning.local_dir`** (default `<planning home>/local`; `ABK_LOCAL_DIR` and `abk.local.yaml` override, like `planning.home` and `planning.state_dir`). It holds `unit-graphs.sqlite`, `locks/`, `leases/`, the e2e-test lock and `environment.lock`, and the change locks `task-progress-is-tracked-in-the-state-home-and-archived-to-the-repo` puts under `locks/changes/`. `planning.state_dir` then holds only durable, shareable files. A separate planning repo, whose state stays in `runs/`, defaults `local_dir` to its state directory, so nothing moves for it.
- **Honest locking on a remote mount**: `file_lock` waits at most `ABK_LOCK_WAIT_SECONDS` (default 120) and then raises `LockTimeout`, naming the file, the wait, the setting and the mount type; `atomic_write_*` names its temporary `<name>.<host>.<pid>.tmp`, fsyncs it before `os.replace` and retries a rename the share refuses briefly; lease, branch-lock and e2e-lock records carry the host, and a record from another host is never judged by this host's process table, so it is never stolen.
- **A lock probe** (`abk doctor` always; the tick, once a day, only when the state directory is not on a local filesystem): two processes each open the same file under the state directory and ask `flock` for it. If both get it, or the answer is an error, the check fails (doctor) or the tick refuses to start (exit 1, nothing written), naming the mount type and what to change.
- **Docs and doctor**: a "network drive" section in `docs/configuration.md`, the doctor's `local dir`, `state locking` and `state mount` checks, the architecture's "State on disk" table, and the changelog.

## Impact

- Capabilities: `planning-local-directory`, `state-locking-on-a-share`, `lock-holder-hosts` (new).
- agent-build-kit: `installation.py`, `config.py` (`PlanningConfig.local_dir`), `settings.py`, `graph/checkpointer.py`, `pipeline/file_lock.py`, `pipeline/lease.py`, `pipeline/workspaces.py`, `pipeline/e2e.py`, `pipeline/environment.py`, `cli/pipeline.py`, `cli/doctor.py`, new `pipeline/host.py`, `pipeline/mounts.py` and `pipeline/lock_probe.py`, `tests/`, `docs/`, `CHANGELOG.md`.
- Not in this change: two hosts running ticks, timers or `abk serve` against one state directory (still unsupported); a share-side lock service; moving the unit worktrees or the pipeline worktree (they stay local, outside the state); an override that runs on a share the probe refused.
