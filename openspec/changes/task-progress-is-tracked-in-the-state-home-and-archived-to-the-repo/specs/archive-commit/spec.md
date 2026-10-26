## ADDED Requirements

### Requirement: The archive writes the final files and commits its result

Before `openspec archive` of a change, the archive step SHALL reconcile the tracking copy and write its `tasks.md` and, when it exists, its `follow-ups.md` over the repository files. When the archive succeeds, the step SHALL commit the change's archived directory, the synced main specs and nothing else, and publish the commit as `planning.publish` says: `direct` pushes to the default branch (the current branch for a working copy or a separate planning repo), `branch` pushes `planning/archive-<change>-<run id>` and opens a pull request to it. The commit SHALL be limited to `<specs dir>/changes/<change>`, `<specs dir>/changes/archive` and `<specs dir>/specs`: never `abk.yaml`, the state directory or any code path. A failed `openspec archive` SHALL restore the repository files and commit nothing. A rejected push SHALL be retried once after a fetch and a rebase onto the remote branch; a second rejection SHALL keep the commit, be logged with the path of the checkout, and not fail the tick. The push, retry and pull-request code SHALL be the one the tracks' bookkeeping commit uses. After a published commit the copy SHALL be removed.

#### Scenario: A fully merged change is archived and published

- **GIVEN** a change whose units have all merged, a tracking copy with every group ticked and follow-ups, and `planning.publish: direct`
- **WHEN** the tick archives it
- **THEN** the default branch has one commit holding the archived directory with the ticked `tasks.md` and the `follow-ups.md`, the removal of the active directory and the synced main specs, `abk.yaml` and the state directory are not in it, and the worktree has no modified tracked file

#### Scenario: A person pushed in between

- **GIVEN** the default branch moved since the worktree's last sync, without touching the change
- **WHEN** the archive commit is pushed
- **THEN** the first push is rejected, the commit is rebased onto the new tip and pushed, and a conflict ends in the commit kept and the rejection logged

#### Scenario: Publish by branch

- **GIVEN** `planning.publish: branch`
- **WHEN** a change is archived
- **THEN** `planning/archive-<change>-<run id>` is pushed, a pull request to the default branch is opened with a title naming the change, HEAD is put back where it was with the files left in the worktree, and the next sync fast-forwards once the pull request merges

#### Scenario: A change with no follow-ups

- **GIVEN** a change that recorded no follow-ups
- **WHEN** it is archived
- **THEN** the archived directory has no `follow-ups.md` and the commit has the ticked `tasks.md`

#### Scenario: The archive fails

- **GIVEN** `openspec archive` exits non-zero
- **WHEN** the step runs
- **THEN** the repository `tasks.md` is as it was before the copy-back, no commit is made and the change is tried again at the next tick

#### Scenario: A manual verify

- **GIVEN** `abk verify <change>` archives the change
- **WHEN** it passes
- **THEN** the archive is committed and published the same way as in a tick

#### Scenario: A separate planning repo with its own default branch

- **GIVEN** a `separate` installation on its default branch
- **WHEN** a change is archived
- **THEN** the commit is pushed to that branch, with the same path limits
