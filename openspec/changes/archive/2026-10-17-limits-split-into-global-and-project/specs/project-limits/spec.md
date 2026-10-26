## ADDED Requirements

### Requirement: A project is a repo's project, and a unit belongs to one

For the limits counted for each project, a project SHALL be the pair of a repo and a project path (the unit's repo and its
project), the root project being `.`. A repo with one project, or none declared, SHALL count as that one project. A unit whose
repo or project the configuration no longer declares SHALL be a project of its own, counted like any other. No count SHALL be
kept across projects, and no limit SHALL be compared with a sum.

#### Scenario: A repo with one project

- **GIVEN** a repo that declares one project
- **WHEN** its units are counted
- **THEN** they are counted together against the project limits, as the repo's were before projects existed

#### Scenario: A project the configuration dropped

- **GIVEN** a stored unit of project `old` that the repo no longer declares
- **WHEN** units are counted
- **THEN** the unit is counted with the other units of `old` as its own project, with the same limits

### Requirement: Build workers are counted for each project

Each project SHALL have its own `max_concurrent_stacks` build workers: a unit SHALL start only while fewer than that many units of
its own project are being built, units being built in another project SHALL NOT take a worker from it, and a pass SHALL keep every
project's workers full independently. The set of workers a pass owns SHALL be at least as large as every project's workers
together. Units resumed or moved for a restack SHALL take a worker of their own project.

#### Scenario: Two projects build side by side

- **GIVEN** two projects each with four ready units and a limit of 4 workers
- **WHEN** a pass starts units
- **THEN** four units of each project are building, eight in all

#### Scenario: One project's workers are full

- **GIVEN** a project with its workers all busy and another with one busy
- **WHEN** a unit of each is ready
- **THEN** the busy project's unit waits and the other's starts

#### Scenario: A resumed unit

- **GIVEN** a unit that resumes where it stopped, in a project whose workers are full
- **WHEN** units are chosen
- **THEN** it waits for a worker of its project and takes none from another

#### Scenario: A repo with one project

- **GIVEN** one repo with one project and a limit of 4 workers
- **WHEN** a pass starts units
- **THEN** no more than four are building, as before

### Requirement: A full project holds back only its own units

When a project is at its limit on units in progress, a unit of it that has never started SHALL be skipped and the next ready unit
considered, so that a ready unit of another project starts in its place; a skipped unit SHALL NOT take a build worker, and the
status SHALL give it the wait reason for a full queue. A unit that is already in progress SHALL continue, as before, in a full
project too.

#### Scenario: The head of the queue belongs to a full project

- **GIVEN** the most urgent ready unit belongs to a full project and a less urgent one to a project with room
- **WHEN** units are chosen
- **THEN** the less urgent one starts and the other waits

#### Scenario: Its wait reason

- **GIVEN** a ready unit of a full project that has never started
- **WHEN** its wait reason is read
- **THEN** it is the full queue, not a slot

#### Scenario: Work in progress in a full project

- **GIVEN** a unit in review in a full project that is sent back for rework
- **WHEN** units are chosen
- **THEN** the rework starts

### Requirement: Restacks run in a lane for each project

Each project SHALL have its own restack lane of `max_concurrent_restacks` workers, in the order its restacks were seen. A
restack of a unit SHALL be handed to the lane of the unit's project and take no worker of another project's lane; a lane that has
nothing to do SHALL cost nothing. A pass SHALL wait for every lane's running and waiting restacks as it waited for the one
lane, and report its restacks in total.

#### Scenario: Two projects restack at once

- **GIVEN** two projects each owed three restacks and a lane of 2
- **WHEN** the restacks are seen
- **THEN** two of each project's run and one of each waits, four running in all

#### Scenario: One project's lane is full

- **GIVEN** a project whose lane is full and a unit of another owed a restack
- **WHEN** it is handed over
- **THEN** it starts at once in its own project's lane

#### Scenario: A repo with one project

- **GIVEN** one repo with one project and a lane of 2
- **WHEN** three restacks are seen
- **THEN** two run and one waits, as before

#### Scenario: The pass waits for every lane

- **GIVEN** restacks running in two projects' lanes
- **WHEN** the pass would otherwise end
- **THEN** it waits until both lanes are idle

### Requirement: The same limits apply to each project of every repo

`project_limits` SHALL be read once and applied to every project of every repo the workspace holds, including a project a repo
gains later. A change to a limit SHALL take effect for every project at the next pass.

#### Scenario: A project added later

- **GIVEN** a limit of 3 units in progress and a repo that registers a second project
- **WHEN** the next pass runs
- **THEN** the new project counts its own units against 3, and the first project's count is unaffected

#### Scenario: A limit changed

- **WHEN** `project_limits.max_units_in_progress` is lowered from 5 to 3
- **THEN** a project with four units in progress starts no new unit and stops none
