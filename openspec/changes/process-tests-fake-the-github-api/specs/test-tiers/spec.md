## ADDED Requirements

### Requirement: A test that runs the CLI fakes the code host at its API

A test that runs `abk` as a process and stands in for GitHub SHALL do so with a fake server speaking
the REST API the forge calls, reached through `ABK_GITHUB_API_URL`, and not with a script
standing in for `gh`. The fake SHALL answer from the recorded GitHub answers the forge tests use,
SHALL require the credential, and SHALL refuse a route it does not serve rather than answer it empty.

#### Scenario: A unit reaches review

- **GIVEN** a scratch unit built through the CLI against the fake host
- **WHEN** the unit's branch is pushed
- **THEN** the fake host holds the pull request the forge created, and the run log says the unit is
  in review

#### Scenario: A route the fake does not serve

- **GIVEN** the forge starts calling a route the fake does not serve
- **WHEN** a process test reaches it
- **THEN** the call fails with an error naming the route, and the test does not pass on an empty answer

#### Scenario: A request without the credential

- **GIVEN** a request that carries no valid token
- **WHEN** it reaches the fake host
- **THEN** it is refused with a 401, as the host does
