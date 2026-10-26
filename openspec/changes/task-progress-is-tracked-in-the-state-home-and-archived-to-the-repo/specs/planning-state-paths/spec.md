## MODIFIED Requirements

### Requirement: Verify of the planning repo's own checkout works in the pipeline worktree and exempts the planning paths

For a repo whose checkout is the planning root in a `pipeline worktree`, verify SHALL use the root as that repo's checkout, accept HEAD detached at the
default branch's tip as being on the default branch, sync the worktree (as the tick does) instead of running `git pull`, and exclude from the dirty check
the specs directory, the state directory, the graph page and the usage page, in addition to the repo's `live_written` paths. A tracked change anywhere else
SHALL still refuse verification, naming the files. For every other repo the checks SHALL be as before.

#### Scenario: Only planning paths are dirty

- **GIVEN** a pipeline worktree at the tip with `runs/units.json`, `docs/unit_graph.md`, an edited `proposal.md` and an archive move modified
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
