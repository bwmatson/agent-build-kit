## ADDED Requirements

### Requirement: A unit's worktree folder is named for the repository's name in abk.yaml

The folder under `planning.worktree_root` that holds a repo's unit worktrees SHALL be the repo's name in `abk.yaml` (`repos.<name>`), with each character other than a letter, digit, `.`, `_` or `-` replaced by `_`, and the unit's worktree SHALL be `<root>/<that folder>/<branch with every non-alphanumeric character replaced by _>`. The same folder SHALL hold the repo's detached checkouts. The folder SHALL NOT depend on the checkout's path, so it is the same when the checkout moves and, for a repo with `path: .`, in the working copy and in the pipeline worktree. A repo whose name equals the last segment of its checkout path SHALL keep the directories it has.

#### Scenario: A repo at an external folder keeps its directories

- **GIVEN** `repos.app` with a checkout at `<dir>/app` and a unit worktree already at `<root>/app/spec_x_1`
- **WHEN** the unit's worktree is looked for and then prepared
- **THEN** it is `<root>/app/spec_x_1`, and nothing is created or moved

#### Scenario: A repo with path dot

- **GIVEN** `repos.lib` with `path: .` in an installation whose root is a folder named `worktree`, and a second `repos.app` at `<dir>/worktree`
- **WHEN** a unit of each is prepared on the same branch name
- **THEN** one is under `<root>/lib/` and the other under `<root>/app/`, and neither shares a folder with the other

#### Scenario: The checkout moves

- **GIVEN** `repos.app` whose checkout was at `<dir>/one` and is now at `<dir>/two`, and a unit worktree at `<root>/app/spec_x_1`
- **WHEN** the unit is resumed
- **THEN** the worktree at `<root>/app/spec_x_1` is used

#### Scenario: A key with a dash

- **GIVEN** a repo named `my-app`
- **WHEN** its worktree folder is named
- **THEN** it is `my-app`

### Requirement: A unit's existing worktree is found through git and used where it is

Whenever the pipeline needs a unit's worktree, to create, resume, restack, retire, attach to, run a manual step in or show it, it SHALL read `git worktree list --porcelain` of the unit's repo and look for the entry on the unit's branch before looking at any path. An entry under `planning.worktree_root`, whatever its folder, whose directory exists SHALL be the unit's worktree and SHALL be used as it stands, never moved or recreated. An entry under the root whose directory is gone SHALL be pruned with `git worktree prune` before a worktree is created under the current folder. With no entry, a worktree SHALL be created under the current folder; if that path exists and is not an empty directory the pipeline SHALL refuse, naming the branch and the path, and SHALL NOT use it.

#### Scenario: A worktree under an earlier folder is adopted

- **GIVEN** a unit worktree for `spec/x/1` at `<root>/worktree/spec_x_1`, and a repo whose current folder is `<root>/lib`
- **WHEN** the unit is prepared
- **THEN** `<root>/worktree/spec_x_1` is returned with its commits and uncommitted changes as they were, `<root>/lib` is not created, and git lists no new worktree

#### Scenario: No worktree

- **GIVEN** a branch with no worktree
- **WHEN** the unit is prepared
- **THEN** a worktree is created at `<root>/<repo name>/<sanitised branch>` on the branch

#### Scenario: A registered worktree whose directory was deleted

- **GIVEN** `spec/x/1` registered at `<root>/lib/spec_x_1` whose directory was deleted
- **WHEN** the unit is prepared
- **THEN** the stale registration is pruned and the worktree is created at the current path

#### Scenario: Two branches with one sanitised name

- **GIVEN** a worktree for `spec/a-b/1` at `<root>/lib/spec_a_b_1`
- **WHEN** a unit on `spec/a_b/1` is prepared
- **THEN** the call is refused naming `spec/a_b/1` and `<root>/lib/spec_a_b_1`, and the first worktree is as it was

#### Scenario: A detached checkout under an earlier folder

- **GIVEN** a detached checkout `_dev_stack_base` registered at `<root>/worktree/_dev_stack_base`
- **WHEN** the dev stack's base is prepared for the repo
- **THEN** that directory is moved to the ref and used, and no second one is created

### Requirement: A branch checked out outside the worktree root is refused, never adopted

When the unit's branch is checked out at a path that is not under `planning.worktree_root`, in the repository's own checkout or in another worktree, creating or removing the unit's worktree SHALL be refused with a message naming the branch and that path. The pipeline SHALL NOT use, switch, move or remove that checkout, and SHALL NOT pass `--force` to git. A read-only lookup SHALL report the unit as having no worktree.

#### Scenario: Checked out in the working copy

- **GIVEN** `spec/x/1` checked out in the repo's working copy
- **WHEN** the unit is prepared
- **THEN** the call is refused naming `spec/x/1` and the working copy's path, and the working copy's branch, head and files are as they were

#### Scenario: A probe

- **GIVEN** the same state
- **WHEN** `abk attach` or the review page asks for the unit's worktree
- **THEN** none is reported and nothing is changed

#### Scenario: Retire does not remove it

- **GIVEN** the same state and `abk retire --delete-branch`
- **WHEN** it runs
- **THEN** the checkout is untouched, the failure is reported with the path, and the exit code is 1

### Requirement: abk doctor reports unit worktrees under another folder and registered ones that are gone

`abk doctor` SHALL, for each repo, list the repo's worktrees under `planning.worktree_root`. One in a folder other than the repo's current one SHALL be a note, not a failure, saying it is adopted and may be moved with `git worktree move` while its unit is idle. One whose directory is missing SHALL be a warning naming `git worktree prune`. It SHALL change nothing.

#### Scenario: A legacy folder

- **GIVEN** a unit worktree under `<root>/worktree/` for a repo whose folder is `lib`
- **WHEN** `abk doctor` runs
- **THEN** a note names the worktree and `git worktree move`, and the exit code is unchanged

#### Scenario: A deleted directory

- **GIVEN** a registered worktree under the root whose directory is gone
- **WHEN** `abk doctor` runs
- **THEN** a warning names it and `git worktree prune`, and the registration is still there afterwards

#### Scenario: Nothing to report

- **GIVEN** every unit worktree under its repo's current folder
- **WHEN** `abk doctor` runs
- **THEN** the check is ok
