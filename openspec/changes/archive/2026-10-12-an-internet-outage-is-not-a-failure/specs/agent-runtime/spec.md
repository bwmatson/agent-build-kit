## ADDED Requirements

### Requirement: A runtime reports an unreachable network as its own outcome

When an agent run ends because the network could not be reached — a name that does not resolve, a network or host that is unreachable, a connection
refused or timed out at connect — the runtime SHALL report it as a typed network-unavailable outcome, distinct from a failed call, a refusal, a rate
limit and an interruption, carrying the runtime's own words. It SHALL NOT report an HTTP error status, a model refusal, a usage limit or a tool
failure as such, and SHALL NOT make a model call to decide. A failure that is not that outcome SHALL be reported as before.

#### Scenario: The API cannot be reached

- **GIVEN** an agent run that exits 1 saying it cannot reach the API server because a name did not resolve
- **WHEN** the runtime reads the result
- **THEN** it reports the network as unavailable, with the runtime's words

#### Scenario: An HTTP error is not an outage

- **GIVEN** an agent run that ends on a 401, a 403 or a 404 answer
- **WHEN** the runtime reads the result
- **THEN** it reports an ordinary failed call

#### Scenario: A refusal is not an outage

- **GIVEN** an agent run that ends on a model refusal or a usage limit
- **WHEN** the runtime reads the result
- **THEN** it reports that refusal or limit as before

#### Scenario: Another runtime

- **GIVEN** the ACP runtime and a failed result whose text names a name that could not be resolved
- **WHEN** the runtime reads the result
- **THEN** it reports the network as unavailable the same way

### Requirement: A runtime reports a degraded model service as its own outcome

When an agent run ends on an HTTP status of 500 to 599, an overloaded 529 among them, after the runtime's own retries, the runtime SHALL report it
as a typed service-unavailable outcome carrying the status and the runtime's own words, distinct from a network-unavailable outcome. It SHALL NOT
report a 4xx status, a 401 or 403, a 429 usage or rate limit, a model refusal or a tool failure as such, SHALL NOT make a model call to decide, and
SHALL report a failure whose status it cannot read as before.

#### Scenario: The service is overloaded

- **GIVEN** an agent run whose closing event carries the status 529 after the runtime's own retries
- **WHEN** the runtime reads the result
- **THEN** it reports the service as unavailable, with the status and the runtime's words

#### Scenario: A server error

- **GIVEN** an agent run whose closing event carries the status 500
- **WHEN** the runtime reads the result
- **THEN** it reports the service as unavailable

#### Scenario: A client error is not a degraded service

- **GIVEN** an agent run that ends on a 401, a 403 or a 404 status
- **WHEN** the runtime reads the result
- **THEN** it reports an ordinary failed call

#### Scenario: A rate limit keeps its own path

- **GIVEN** an agent run that ends on a 429 usage or rate limit
- **WHEN** the runtime reads the result
- **THEN** it reports the rate limit as before and not a degraded service

#### Scenario: A refusal is not a degraded service

- **GIVEN** an agent run that ends on a model refusal
- **WHEN** the runtime reads the result
- **THEN** it reports an ordinary failed call

#### Scenario: A failure with no readable status

- **GIVEN** an agent run that exits 1 with words and no HTTP status
- **WHEN** the runtime reads the result
- **THEN** it reports an ordinary failed call
