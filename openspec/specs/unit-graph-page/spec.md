# unit-graph-page Specification

## Purpose
TBD - created by archiving change limits-split-into-global-and-project. Update Purpose after archive.

## Requirements

### Requirement: A repo with more than one project is drawn with a subgraph for each

The unit graph page SHALL draw one subgraph for each repo, as it does. When a repo has more than one project (among those it
declares and those of its units in view), the repo's subgraph SHALL hold one nested subgraph for each project that has a unit in
view, titled with the project's path, `.` for the root, and each unit SHALL be drawn inside its own project's subgraph. A repo with
one project SHALL be drawn exactly as it was before projects existed, with no nested subgraph, and a page for a workspace whose
repos each have one project SHALL be unchanged byte for byte. Edges SHALL be drawn as before: dashed across repos, plain within one,
and a dependency between two projects of one repo is within the repo and SHALL be drawn plain. The legend SHALL say that a repo
with several projects shows one subgraph for each.

#### Scenario: A repo with two projects

- **GIVEN** a repo with projects `.` and `web` and a unit in view in each
- **WHEN** the page is drawn
- **THEN** the repo's subgraph holds two nested subgraphs, one titled `.` and one titled `web`, each holding its own unit

#### Scenario: A repo with one project

- **GIVEN** a workspace whose repos each have one project
- **WHEN** the page is drawn
- **THEN** its text equals the page drawn before projects existed, byte for byte

#### Scenario: A project with nothing in view

- **GIVEN** a repo with two projects and units in view only in one
- **WHEN** the page is drawn
- **THEN** the repo's subgraph holds one nested subgraph, the project's with units, and no empty one

#### Scenario: An edge between two projects of one repo

- **GIVEN** a unit of `web` that depends on a unit of the root project of the same repo
- **WHEN** the page is drawn
- **THEN** the edge is plain, not dashed

#### Scenario: The legend

- **WHEN** the page is drawn
- **THEN** its legend says that a repo with several projects is drawn with a subgraph for each, and the unit-graph document says so too
