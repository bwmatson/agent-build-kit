## ADDED Requirements

### Requirement: Verify of the planning repo's own checkout works in the pipeline worktree and exempts the planning paths

For a repo whose checkout is the planning root in a `pipeline worktree`, verify SHALL use the root as that repo's checkout, accept HEAD detached at the
default branch's tip as being on the default branch, sync the worktree (as the tick does) instead of running `git pull`, and exclude from the dirty check
the specs directory, the state directory, the graph page and the usage page, in addition to the repo's `live_written` paths. A tracked change anywhere else
SHALL still refuse verification, naming the files. For every other repo the checks SHALL be as before.

#### Scenario: Only planning paths are dirty

- **GIVEN** a pipeline worktree at the tip with `runs/units.json`, `docs/unit_graph.md`, a ticked `tasks.md` and an archive move modified
- **WHEN** a change that touched this repo is verified
- **THEN** the dirty check passes and verification goes on

#### Scenario: A code edit is dirty

- **GIVEN** the same and a modified source file
- **WHEN** a change is verified
- **THEN** verification refuses, naming the source file and no other

#### Scenario: Detached at the tip

- **GIVEN** HEAD detached at `origin/main`'s tip
- **WHEN** a change is verified
- **THEN** the branch test passes, and a HEAD not at the tip fails it with the commits it lacks named

#### Scenario: Another repo

- **GIVEN** a verified change on a repo that is not the planning root's
- **WHEN** it is verified
- **THEN** the branch test, the dirty test and `git pull --ff-only` are as before

### Requirement: Planning commits are limited to the planning paths

In an in-repo installation, a planning commit (the chat's and attach's `commit_planning`) SHALL stage and commit only the specs directory, the state directory, the graph page,
the usage page and `abk.yaml`, and the count the chat shows as planning changes SHALL count only those paths. A modified or untracked file outside
them SHALL be left unstaged and untouched. The gate and the lock cleanup SHALL run as before. In a `separate` installation the commit and the count SHALL
be as before. A unit's own commits SHALL still stage everything in its worktree.

#### Scenario: Code edits in progress

- **GIVEN** an in-repo working tree with a modified change and a modified source file
- **WHEN** the planning commit is made
- **THEN** the commit holds the change and not the source file, which is still modified and unstaged

#### Scenario: The count

- **GIVEN** the same tree
- **WHEN** the chat counts planning changes
- **THEN** the source file is not counted

#### Scenario: Nothing in the planning paths

- **GIVEN** only a source file modified
- **WHEN** the planning commit is made
- **THEN** it reports nothing to commit and creates no commit

#### Scenario: A separate planning repository

- **GIVEN** a `separate` root with a modified file anywhere
- **WHEN** the planning commit is made
- **THEN** it is committed as before

#### Scenario: A unit's commit

- **GIVEN** a unit worktree with modified files
- **WHEN** the unit's commit is made
- **THEN** every change in it is staged as before

### Requirement: A unit worktree of the planning repo cannot write the planning paths

For a unit whose repo is the planning repo, the tool policy SHALL deny a file write whose path inside the unit's own worktree is the specs directory,
the state directory, the graph page, the usage page or the top-level `abk.yaml`, with a message saying that the pipeline owns them and to report
`BLOCKED: <what and where>`. Every other path in the worktree, including a file named `abk.yaml` nested in a fixture, SHALL remain writable. A unit of another repo
SHALL be unaffected.

#### Scenario: A write to the specs

- **GIVEN** a unit worktree of the planning repo
- **WHEN** its agent writes `openspec/changes/<change>/tasks.md` inside that worktree
- **THEN** the write is denied with the BLOCKED message

#### Scenario: A write to the configuration

- **GIVEN** the same
- **WHEN** its agent writes the worktree's `abk.yaml` or `runs/units.json`
- **THEN** each write is denied

#### Scenario: A nested file of the same name

- **GIVEN** the same
- **WHEN** its agent writes `tests/fixtures/x/abk.yaml`
- **THEN** the write is allowed

#### Scenario: Code

- **GIVEN** the same
- **WHEN** its agent writes `src/module.py`
- **THEN** the write is allowed

#### Scenario: A unit of another repo

- **GIVEN** a unit of a repo that is not the planning repo with a file `openspec/x.md` in its worktree
- **WHEN** its agent writes it
- **THEN** the write is allowed

### Requirement: `locate()` does not adopt a unit worktree's `abk.yaml`

When neither `--config` nor `ABK_CONFIG` is given and the nearest `abk.yaml` is in a linked worktree whose checked-out branch matches the unit branch
pattern of that file (`git.branch_prefix`, then `<change>/<n>`), `locate()` SHALL NOT return it. It SHALL return the pipeline worktree's `abk.yaml` when the
repository has a live marker, and otherwise raise a configuration error naming the unit worktree and telling the caller to pass `--config` or set
`ABK_CONFIG`. A linked worktree on any other branch, a detached one, and a main working tree SHALL be found as before.

#### Scenario: A hand-run command in a unit worktree

- **GIVEN** a unit worktree on `spec/<change>/1` with its own `abk.yaml`, and a live pipeline worktree
- **WHEN** `locate()` runs there with no config given
- **THEN** it returns the pipeline worktree's `abk.yaml`

#### Scenario: No live installation

- **GIVEN** the same with no marker
- **WHEN** `locate()` runs
- **THEN** it raises an error naming the worktree and the two ways to name a config

#### Scenario: A config named

- **GIVEN** the same and `ABK_CONFIG` set, as agents get it
- **WHEN** `locate()` runs
- **THEN** it returns that file

#### Scenario: Another branch

- **GIVEN** a linked worktree on a branch that does not match the pattern
- **WHEN** `locate()` runs there
- **THEN** it returns that worktree's `abk.yaml` as before

#### Scenario: A detached unit worktree

- **GIVEN** a unit worktree on a detached HEAD
- **WHEN** `locate()` runs there
- **THEN** it returns that worktree's `abk.yaml` as before, which is the documented gap
