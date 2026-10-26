## ADDED Requirements

### Requirement: A group heading may name the project after the repo

A task group's heading SHALL be able to name the project its work belongs to by writing it after the repo in the first tag, as
`[<repo>/<project>]`, where `<project>` is the `path` the repo declares for that project (relative to the repo root, `/`
separated, with no leading `./` or trailing `/`, so `web` or `services/api`). The first `/` after a declared repo's name SHALL
divide the tag, except that a tag that is itself a declared repo's name SHALL be that repo whole. A heading with the plain
`[<repo>]` tag SHALL belong to the repo's root project, which SHALL never be written in a tag: `[<repo>/.]` SHALL be refused.
The project tag SHALL change nothing else about the heading: the tier, the flag and the title are read as before, and a group's
number, estimate and `Needs:` lines are unaffected.

#### Scenario: A group for a project of the repo

- **GIVEN** a repo that declares a project at `web`
- **WHEN** a heading reads `## 2. [app/web] [tier1] Add the filter`
- **THEN** the group is read as repo `app`, project `web`, tier `tier1`

#### Scenario: A group with no project tag

- **WHEN** a heading reads `## 1. [app] [tier1] Add the route`
- **THEN** the group is read as repo `app`, in the repo's root project

#### Scenario: A project at a nested path

- **GIVEN** a repo that declares a project at `services/api`
- **WHEN** a heading is tagged `[app/services/api]`
- **THEN** the group is read as repo `app`, project `services/api`

#### Scenario: The root project is never written

- **WHEN** a heading is tagged `[app/.]`
- **THEN** the heading is refused with a message that the root project is the untagged one

#### Scenario: A repo whose name holds a slash

- **GIVEN** a declared repo named `team/app`
- **WHEN** a heading is tagged `[team/app]`
- **THEN** the group is read as that repo's root project, not as project `app` of a repo `team`

#### Scenario: The flag and tier are read as before

- **WHEN** a heading reads `## 3. [app/web] [tier2] [acceptance] Drive the page`
- **THEN** the group has project `web`, tier `tier2` and the `acceptance` flag

### Requirement: A project the repo does not declare is refused

A heading whose tag names a project the repo does not declare SHALL be refused by the tag check that `abk tags` runs and by
every planning path that validates a change's groups, with a message that names the group, the project and the repo and lists
the projects the repo does declare. A repo that declares only its root project SHALL say so. No group SHALL be planned from a
change with such a heading.

#### Scenario: An undeclared project

- **GIVEN** a repo `app` that declares projects `.` and `web`
- **WHEN** `abk tags` reads a heading tagged `[app/mobile]`
- **THEN** it reports group N as having unknown project `mobile` for repo `app`, lists `web` as the declared project, and exits 1

#### Scenario: A repo with only a root project

- **GIVEN** a repo that declares no project beyond its root
- **WHEN** a heading is tagged `[app/web]`
- **THEN** the message says the repo declares only its root project, which is tagged `[app]`

#### Scenario: An unknown repo is still refused as before

- **WHEN** a heading is tagged `[nothing/web]` and no repo has that name
- **THEN** the message is the unknown-repo message with the declared repos, not a project message

#### Scenario: Planning refuses it

- **WHEN** a change with a heading for an undeclared project is planned
- **THEN** the plan is refused with the same message and no planner call is made

#### Scenario: The listing prints the project

- **WHEN** `abk tags` lists a valid change whose group is tagged `[app/web]`
- **THEN** its line reads `2. [app/web] [tier1] <title>`

### Requirement: A unit has one project, taken from its groups

A unit SHALL record one project, the `path` of the project its groups are tagged for, `.` for the root project. A unit's groups
SHALL all carry the same repo and the same project: a group tagged for another project SHALL start a new unit, as one tagged for
another repo does, and a plan that gives a unit a group of another project SHALL be refused. A unit stored before projects
existed SHALL read as being in the root project. A re-plan SHALL leave a started unit's project as it was, and a change to the tag
of a group a started unit carries SHALL be reported and not applied, as a changed repo or tier is.

#### Scenario: Two projects of one repo in a row

- **GIVEN** a change whose groups 1 and 2 are tagged `[app]` and `[app/web]`, both small and in sequence
- **WHEN** the groups are planned into units
- **THEN** they are two units, one in the root project and one in `web`

#### Scenario: Two groups of one project join as before

- **GIVEN** two small groups in sequence both tagged `[app/web]` and `[tier1]`
- **WHEN** the groups are planned into units
- **THEN** one unit carries both and records project `web`

#### Scenario: A plan that mixes projects

- **WHEN** the planner's reply gives one unit groups tagged for two projects, or a project that differs from its groups'
- **THEN** the plan is refused, naming the unit, the group and the two projects

#### Scenario: A stored unit from before projects

- **GIVEN** a stored unit with no project recorded
- **WHEN** the store is read
- **THEN** the unit's project is `.`, and the next write records it

#### Scenario: A re-plan keeps a started unit's project

- **GIVEN** a unit that has started and whose group is still tagged for its project
- **WHEN** the change is planned again
- **THEN** the unit's project is unchanged

### Requirement: The planner is told each group's project and may not join across projects

The planning prompt SHALL tell the planner that a unit is in one repo and one project, show each group's project, and say that
groups tagged for different projects are never grouped or joined. The units already in flight that the planner is shown SHALL
carry their project. A join the planner proposes between two units, or a unit and a group, of different projects SHALL be
refused as a join across repos is.

#### Scenario: The prompt names the project

- **WHEN** the planner is asked to plan a change with a group tagged `[app/web]`
- **THEN** the prompt shows that group as project `web` and says units never span projects

#### Scenario: A join across projects

- **WHEN** the planner proposes joining an unstarted unit of project `web` with one of the root project in the same repo and tier
- **THEN** the join is refused and the plan is rejected as a join that breaks a rule

#### Scenario: Units in flight

- **WHEN** the planner is shown the units in flight
- **THEN** each entry carries its repo and its project

### Requirement: A project is named where a person reads a unit

Where `abk status` names a unit's repo (the ready queue, a failed unit, a blocked unit, a unit waiting on a second parent),
it SHALL name the repo and project as `<repo>/<project>` when that repo has more than one project, the root project as the repo's
own name, and SHALL name the repo alone when it has one. `abk project init` SHALL say, when it registers a project, that groups
for it are tagged `[<repo>/<path>]` and that its units are counted apart from the repo's other projects.

#### Scenario: A repo with two projects

- **GIVEN** a repo with projects `.` and `web` and a failed unit in `web`
- **WHEN** the status is printed
- **THEN** the failed line names the unit as `(app/web)`

#### Scenario: A repo with one project

- **WHEN** the status names a unit of a repo with one project
- **THEN** it reads `(app)`, as before

#### Scenario: Registering a project

- **WHEN** `abk project init web --repo app --profile <profile>` registers a project
- **THEN** its output says groups for it are tagged `[app/web]` and its units count apart from the repo's other projects
