## ADDED Requirements

### Requirement: A group is built by at most one unit that has not finished

A task group SHALL be carried, as a unit's own group or a joined one, by at most one unit that has not finished and has started. A unit owns its groups while it is
`planned`, `running`, `in_review`, `failed` or `held`, or `unplanned` with a branch, a pushed commit, a pull request or an approval. A merged, closed,
satisfied or retired unit, and an `unplanned` unit with no work, owns none. `UnitStore.upsert` SHALL refuse a plan that gives a group to a unit that
did not carry it before while a unit that has started and owns it carries it, naming both units and the group. The refusal SHALL be of the whole
change plan: nothing SHALL be written for the change, the log SHALL give the way out (`abk retire` for the owner, or an edit of `tasks.md` that keeps the group
with it), the plan SHALL be recorded as failed with its attempts spent so the model is not asked again until something changes, and `abk replan` SHALL exit 1.
A collision already in the store SHALL NOT make a plan fail. Reshaping, joining and splitting units that have not started SHALL be as before.

#### Scenario: A new unit may not take a started unit's group

- **GIVEN** a planned unit `app/3` with a branch that carries group 16, and a plan that omits `app/3` and gives group 16 to a new unit `app/4`
- **WHEN** the plan is applied
- **THEN** it is refused, the store is unchanged, the message names `app/3`, `app/4` and group 16, and `abk replan` exits 1

#### Scenario: A released or finished owner is free

- **GIVEN** the same plan and `app/3` merged, closed, satisfied, retired, or `unplanned` with no work
- **WHEN** the plan is applied
- **THEN** it is accepted

#### Scenario: A unit that has not started may be reshaped

- **GIVEN** an unstarted planned unit that carries group 16 and a plan that gives group 16 to another unit
- **WHEN** the plan is applied
- **THEN** it is accepted, as before this change

#### Scenario: A collision already stored does not block a replan

- **GIVEN** two units that each carry group 8 and are both stored, and a plan that does not change who carries it
- **WHEN** the plan is applied
- **THEN** it is accepted and the status lists the collision

#### Scenario: The tick does not ask again

- **GIVEN** a refused plan and an unchanged `tasks.md`
- **WHEN** the next tick runs
- **THEN** the planner is not called, and the plan is planned when `abk retire` has ended the owner

#### Scenario: A superseding split is not refused

- **GIVEN** a held unit superseded by pieces, so that it is `closed` and its pieces carry its groups
- **WHEN** a plan keeps the pieces
- **THEN** it is accepted, since a closed unit owns no group

### Requirement: A person can retire a unit that has not finished

`abk retire UNIT [--reason TEXT] [--delete-branch] [--discard-unpushed] [--dry-run]` SHALL end a unit that is `planned`, `unplanned`, `failed`, `held`
or `in_review` by setting it to the state `retired` with the cause `retired`. It SHALL refuse, changing nothing and exiting 1, a unit that is merged,
closed, satisfied or retired, a unit that is `running`, a unit whose branch lock is held by a live process or that has a live lease (naming the holder,
since the person stops it first), and a unit that a started same-repo dependent is stacked on (naming the dependent). It SHALL exit 2 for an unknown unit.
The history SHALL record the state, the cause, the reason when one is given and that the command did it, and SHALL NOT record a person's name. The unit's
thread SHALL be deleted. The command SHALL decide every refusal before it changes anything.

#### Scenario: An orphan unit is retired

- **GIVEN** an `unplanned` unit with a local branch and no pull request, whose groups a merged unit carries
- **WHEN** `abk retire app/3 --reason "built in app/4"` runs
- **THEN** the unit is `retired`, its branch and worktree are untouched, and the history has the reason and the cause `retired`

#### Scenario: A running unit is refused

- **GIVEN** a unit that is `running`, or whose branch lock names a live process
- **WHEN** `abk retire` runs on it
- **THEN** it exits 1, names the holder, and the unit is unchanged

#### Scenario: A finished unit is refused

- **GIVEN** a merged unit
- **WHEN** `abk retire` runs on it
- **THEN** it exits 1 and says the unit is finished

#### Scenario: A started dependent refuses it

- **GIVEN** a unit that another started unit is stacked on
- **WHEN** `abk retire` runs on it
- **THEN** it exits 1 and names the dependent

#### Scenario: A stale lock does not refuse

- **GIVEN** a branch lock left by a process that is gone
- **WHEN** `abk retire` runs on the unit
- **THEN** it retires the unit

### Requirement: A retired unit is finished and builds nothing

A `retired` unit SHALL NOT count as in progress and SHALL NOT take a place under the limit on units in progress. A unit that depends on it, or that follows it
as an acceptance or narrow unit, SHALL NOT wait on it. Its groups SHALL NOT be counted as a later unit's. A plan SHALL NOT revive, reshape or reuse it: the planner
SHALL be shown its id as taken and a plan using the id SHALL be refused as an invalid plan. The graph, the units listing and the status SHALL show it as
retired and finished. A change SHALL be ready to archive with a retired unit among its units only when every group that unit carried is also carried by a
merged or satisfied unit.

#### Scenario: It holds no place

- **GIVEN** a limit of 5, four counted units and a retired unit with a branch
- **WHEN** the count and the room are worked out
- **THEN** the count is 4 and the room is 1

#### Scenario: A dependent does not wait

- **GIVEN** a planned unit that depends on a retired unit
- **WHEN** readiness is worked out
- **THEN** it is not waiting on it

#### Scenario: A plan cannot use its id

- **GIVEN** a retired unit `app/3` and a plan from the planner that uses the id `app/3`
- **WHEN** the plan is checked
- **THEN** it is refused as invalid, naming the id

#### Scenario: A change archives once its groups are built elsewhere

- **GIVEN** a change whose units are merged or retired, every group of the retired ones carried by a merged unit
- **WHEN** the archive is considered
- **THEN** the change is ready to archive

#### Scenario: A change with unbuilt retired groups waits

- **GIVEN** a retired unit whose group no merged or satisfied unit carries
- **WHEN** the archive is considered
- **THEN** the change is not ready, until a unit that builds the group has merged

#### Scenario: It is shown as retired

- **GIVEN** a retired unit with a branch
- **WHEN** the status, the graph and the units listing are read
- **THEN** each shows it as retired and none as in progress

### Requirement: Retiring a unit releases its groups and names the work that was not built

`abk retire` SHALL print, for each group the unit carries, whether another unit carries it (naming that unit, merged or still owning it) or no unit does.
When any group is carried by no unit, the work was not built: the command SHALL refuse unless `--reason` is given, SHALL print those groups, and with a reason
SHALL print them as released. It SHALL forget the recorded plan of every change whose groups were released and of every change whose recorded refusal names
the unit, so the next tick plans them again. It SHALL list the units that depend on the retired unit and have not finished, with their states, as no longer
waiting. A unit whose groups are all carried SHALL need no reason.

#### Scenario: A built group is carried

- **GIVEN** a unit whose group is carried by a merged unit
- **WHEN** `abk retire` runs without a reason
- **THEN** the unit is retired and the output says the group is in the merged unit

#### Scenario: Unbuilt work needs a reason

- **GIVEN** a unit with a group no other unit carries
- **WHEN** `abk retire` runs without `--reason`
- **THEN** it exits 1, prints the group and the change, and changes nothing

#### Scenario: Unbuilt work with a reason is released and planned again

- **GIVEN** the same unit
- **WHEN** `abk retire --reason "narrowed"` runs and the next tick plans
- **THEN** the unit is retired, the group is printed as released, the change's recorded plan is forgotten, and the plan gives the group to a unit

#### Scenario: Dependents are listed

- **GIVEN** a planned unit that depends on the unit
- **WHEN** `abk retire` runs
- **THEN** the dependent is listed with its state as no longer waiting

### Requirement: Retiring closes the pull request and keeps the branch unless asked

When the retired unit has an open pull request the command SHALL close it with the reason posted first, by the call a satisfied unit's pull request is
closed by, and a close that fails SHALL be kept as pending and repeated each pass, the unit staying retired. The command SHALL keep the unit's branch, its
remote branch and its worktree unless `--delete-branch` is given. With it, the command SHALL remove the worktree (never forced; a worktree with uncommitted
changes SHALL refuse the command before anything changes), delete the local branch and delete the remote branch through the forge when the unit was pushed.
A branch with commits after its last pushed commit (after its base when none was pushed) SHALL refuse `--delete-branch` alone, printing the count, and
`--delete-branch --discard-unpushed` SHALL delete it. `--discard-unpushed` without `--delete-branch` SHALL be refused. A failure after the state is
written SHALL leave the unit retired, say what remains, and exit 1.

#### Scenario: A pull request is closed with the reason

- **GIVEN** a unit in review with an open pull request
- **WHEN** `abk retire --reason "superseded"` runs
- **THEN** the reason is posted, the pull request is closed, and the unit is retired

#### Scenario: A close that fails is repeated

- **GIVEN** a host that refuses the close
- **WHEN** `abk retire` runs and then a pass runs once the host answers
- **THEN** the unit is retired after the first and the pull request is closed by the pass

#### Scenario: Nothing is deleted without the flag

- **GIVEN** a unit with a branch, a worktree and a pushed remote branch
- **WHEN** `abk retire` runs without `--delete-branch`
- **THEN** the branch, the worktree and the remote branch are all still there

#### Scenario: Unpushed commits are counted and need a second flag

- **GIVEN** a branch with 3 commits after its last pushed commit
- **WHEN** `abk retire --delete-branch` runs
- **THEN** it exits 1 before changing anything and prints `3 commits not pushed`, and with `--discard-unpushed` as well the branch is deleted

#### Scenario: A dirty worktree refuses the deletion

- **GIVEN** a worktree with uncommitted changes
- **WHEN** `abk retire --delete-branch` runs
- **THEN** it exits 1 before changing anything

#### Scenario: Dry run changes nothing

- **GIVEN** any unit
- **WHEN** `abk retire UNIT --dry-run --delete-branch` runs
- **THEN** it prints each step, the groups released, the dependents and the commit count, writes nothing, calls no host and exits as the real run would

### Requirement: The status shows which units to retire

`abk status` SHALL list each group carried by two units that have not finished and have started, naming both with their states, and each `unplanned` unit that
holds work, each with the `abk retire` line to run. For a collision the line SHALL suggest the unit further from done and say it is a suggestion. For an
`unplanned` unit whose groups a merged unit carries it SHALL say nothing is lost. It SHALL print nothing of this kind for a store without them, and the
listing SHALL NOT change the exit status.

#### Scenario: An orphan is listed with its command

- **GIVEN** an `unplanned` unit with a branch whose group a merged unit carries
- **WHEN** `abk status` runs
- **THEN** the unit is listed with `abk retire <unit> --reason "..."` and a note that its groups are in the merged unit

#### Scenario: A collision is listed

- **GIVEN** a planned unit with a branch and a unit in review that both carry group 8
- **WHEN** `abk status` runs
- **THEN** the group and both units are listed, and the planned one is suggested for retiring

#### Scenario: A clean store prints nothing

- **GIVEN** a store with no such unit
- **WHEN** `abk status` runs
- **THEN** the output has no line of this kind
