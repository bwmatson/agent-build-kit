## ADDED Requirements

### Requirement: An in-repo installation keeps its state in a planning home outside the repository

In an in-repo installation (the planning root's repository holds a listed repo), in the working copy and in the pipeline worktree alike, the planning home SHALL default to `<data home>/<repository name>/planning`, where `<repository name>` is the directory name of the repository's main working tree and `<data home>` is `~/.local/share`. The state directory SHALL default to `<planning home>/state`, and the pipeline worktree SHALL be `<planning home>/worktree`. `planning.state_dir` SHALL be optional, so that an unset value is told from `runs`. A separate planning repo, and a root that is in no git repository, SHALL keep `runs` under the root.

#### Scenario: The default in a working copy

- **GIVEN** an in-repo installation named `app` with no state setting
- **WHEN** the installation is loaded from the working copy
- **THEN** `state_dir` is `~/.local/share/app/planning/state`

#### Scenario: The same state from the pipeline worktree

- **GIVEN** the same installation with its pipeline worktree
- **WHEN** it is loaded with `--config <worktree>/abk.yaml`
- **THEN** `state_dir` is the same path as from the working copy

#### Scenario: A separate planning repo

- **GIVEN** a planning repo that holds no listed repo
- **WHEN** it is loaded
- **THEN** `state_dir` is `<root>/runs`, as before

#### Scenario: A tracked runs setting is honoured

- **GIVEN** an in-repo installation whose `abk.yaml` sets `planning.state_dir: runs`
- **WHEN** it is loaded
- **THEN** `state_dir` is `<root>/runs`

### Requirement: The planning home and the state directory are set by environment, local file or tracked file

`ABK_PLANNING_HOME` and `ABK_STATE_DIR` SHALL override `planning.home` and `planning.state_dir` of the ignored `abk.local.yaml`, which SHALL override those of a tracked `abk.yaml`, which SHALL override the default. `planning.home` SHALL move the state directory and the worktree together; `planning.state_dir` SHALL move only the state, and both SHALL accept an absolute or a `~` path. A `planning.home` inside the planning repo SHALL be refused with a configuration error naming it, as `planning.worktree_root` is. `abk doctor` SHALL warn that `planning.home`, or a `planning.state_dir` that is absolute, `~`-led or outside the repository, in a tracked `abk.yaml` is a machine fact, and `abk config --migrate` SHALL move both keys to `abk.local.yaml`. A relative `planning.state_dir` inside the repository SHALL NOT be reported. Both keys SHALL be scrub terms like `planning.worktree_root`.

#### Scenario: Environment wins

- **GIVEN** `abk.local.yaml` setting `planning.state_dir: /a` and `ABK_STATE_DIR=/b`
- **WHEN** the installation is loaded
- **THEN** `state_dir` is `/b`

#### Scenario: The local file wins over the tracked file

- **GIVEN** `abk.yaml` setting `planning.home: /x` and `abk.local.yaml` setting `planning.home: /y`
- **WHEN** the installation is loaded
- **THEN** the state directory is `/y/state` and the worktree path is `/y/worktree`

#### Scenario: The state alone

- **GIVEN** `planning.state_dir: ~/s` and no home setting
- **WHEN** the installation is loaded
- **THEN** `state_dir` is `~/s` expanded and the worktree path is still under the default planning home

#### Scenario: A home inside the repository

- **GIVEN** `planning.home` naming a directory inside the planning repo
- **WHEN** the installation is loaded
- **THEN** it fails with a configuration error naming `planning.home`

#### Scenario: A tracked machine fact

- **GIVEN** a tracked `abk.yaml` with an absolute `planning.state_dir`
- **WHEN** `abk doctor` runs and then `abk config --migrate`
- **THEN** the doctor warns that the key is a machine choice, and the migration moves it to `abk.local.yaml`

#### Scenario: A relative state directory is not a machine fact

- **GIVEN** a tracked `planning.state_dir: runs`
- **WHEN** `abk doctor` runs
- **THEN** it reports nothing for that key

### Requirement: The generated pages default into the state directory

`planning.graph_page` and `planning.usage_page` SHALL be optional. When unset and the state directory is outside the planning root, they SHALL be `<state>/pages/unit_graph.md` and `<state>/pages/unit_cost.md`; otherwise they SHALL be `docs/unit_graph.md` and `docs/unit_cost.md`. A value that is set SHALL be used as it is.

#### Scenario: Pages beside the state

- **GIVEN** an in-repo installation with the default state directory
- **WHEN** a tick writes the graph and cost pages
- **THEN** they are `<state>/pages/unit_graph.md` and `<state>/pages/unit_cost.md` and the repository is untouched

#### Scenario: A separate repo keeps its pages

- **GIVEN** a separate planning repo with no page settings
- **WHEN** the pages are written
- **THEN** they are `docs/unit_graph.md` and `docs/unit_cost.md`

#### Scenario: A set path is kept

- **GIVEN** `planning.graph_page: docs/graph.md` in an in-repo installation
- **WHEN** the graph page is written
- **THEN** it is `<root>/docs/graph.md`

### Requirement: install-timers migrates a worktree in the old place

`abk install-timers` SHALL place the pipeline worktree at `<planning home>/worktree`. When the pipeline marker, or the previous default `<data home>/<repository name>/planning`, names an existing worktree of the repository that is the planning home itself, `install-timers` SHALL move it with `git worktree move` through a temporary name (the new path is inside the old one), rewrite the marker to the new path and then write the unit files for the new `WorkingDirectory`. It SHALL refuse, changing nothing and naming `systemctl --user stop`, when any unit of the installation is active. A second run SHALL change nothing and say the worktree is in place. `--dry-run` SHALL print `would move <old> to <new>` and write nothing. A failure after the first move SHALL put the worktree back. A path at the new location that is not a worktree of the repository SHALL be refused as other occupied paths are.

#### Scenario: An old worktree is moved

- **GIVEN** a worktree at `<data home>/app/planning` named by the marker, with no unit active
- **WHEN** `abk install-timers` runs
- **THEN** the worktree is at `<data home>/app/planning/worktree`, `git worktree list` shows it there, the marker names it and every unit file's `WorkingDirectory` is the new path

#### Scenario: A running unit refuses the move

- **GIVEN** the same with the tick service active
- **WHEN** `abk install-timers` runs
- **THEN** it exits 1 naming the active unit and `systemctl --user stop`, and the worktree, the marker and the units are as before

#### Scenario: A second run

- **GIVEN** a worktree already at the new path
- **WHEN** `abk install-timers` runs
- **THEN** nothing is moved, the marker and units are unchanged, and the output says the worktree is in place

#### Scenario: A dry run

- **GIVEN** an old worktree
- **WHEN** `abk install-timers --dry-run` runs
- **THEN** it prints `would move` with both paths and nothing on disk changes

#### Scenario: A fresh install

- **GIVEN** no marker and no worktree
- **WHEN** `abk install-timers` runs
- **THEN** the worktree is created at `<planning home>/worktree`

#### Scenario: An occupied new path

- **GIVEN** a directory at the new path that is not a worktree of the repository
- **WHEN** `abk install-timers` runs
- **THEN** it exits 1 naming the path and moves nothing
