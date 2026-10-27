## MODIFIED Requirements

### Requirement: Names and machine-local files come from the repository

For a pipeline worktree the unit names and the default `planning.worktree_root` SHALL use the repository's name (the directory name of its main
working tree), not the worktree directory's. A configured `planning.worktree_root` SHALL win. Under the root, each repo's unit worktrees SHALL be in a
folder named for the repo's name in `abk.yaml`, not for its checkout's directory, so the folder is the same in the working copy and in the pipeline
worktree. The `.env` SHALL be the main working tree's when the
pipeline worktree has none, read and never written. A relative `repos.<name>.path` SHALL be relative to the planning root, and an absolute path that is a
worktree of the root's repository SHALL be taken as the root when the root is the pipeline worktree.

#### Scenario: Two installations

- **GIVEN** two repositories named differently, each with a pipeline worktree named `planning`
- **WHEN** their units are rendered
- **THEN** the unit names differ and each default worktree root is under its own repository's name

#### Scenario: A configured worktree root

- **GIVEN** `planning.worktree_root` set
- **WHEN** the root is the pipeline worktree
- **THEN** the unit worktrees are placed under the configured directory

#### Scenario: The same folder from both roles

- **GIVEN** `repos.lib` with `path: .`, and a unit worktree made from the working copy
- **WHEN** the unit is looked up from the pipeline worktree, whose directory has another name
- **THEN** the same worktree is found, under the folder `lib`

#### Scenario: The environment file

- **GIVEN** the main working tree holds `.env` and the pipeline worktree does not
- **WHEN** the installation reads its environment file
- **THEN** it reads the main working tree's, and nothing is written there

#### Scenario: A relative repo path

- **GIVEN** `repos.<name>.path: .` and the pipeline worktree as root
- **WHEN** the repo's checkout is asked
- **THEN** it is the pipeline worktree
