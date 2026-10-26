## ADDED Requirements

### Requirement: Each fake GitHub route is defined once

The in-process fake host and the HTTP fake server SHALL answer every route through one table of method, path pattern and
handler over one state, SHALL NOT keep pull request state in two places, and a route scripted by a test SHALL override the
table for that test only. A request no handler serves SHALL be a 404 recorded as unrouted.

#### Scenario: A route used by both hosts

- **WHEN** the in-process host and the HTTP server are asked for the same route
- **THEN** the same handler answers both from the same state

#### Scenario: A scripted route

- **GIVEN** a test that scripts an answer for a route
- **WHEN** the route is requested in that test
- **THEN** the scripted answer is given, and another test sees the table's

#### Scenario: A route no one serves

- **WHEN** a request matches no scripted route and no handler
- **THEN** the answer is a 404, recorded as unrouted with the method and path

#### Scenario: State written by a test

- **GIVEN** a review with an inline comment written by a test through the server
- **WHEN** the in-process host reads the pull request
- **THEN** it sees the same review and comment

### Requirement: A guard keeps the table the only place

A test SHALL fail if a route handler is registered or answered outside the table.

#### Scenario: A handler added to a host

- **WHEN** a handler is added to a host instead of the table
- **THEN** the guard fails naming it
