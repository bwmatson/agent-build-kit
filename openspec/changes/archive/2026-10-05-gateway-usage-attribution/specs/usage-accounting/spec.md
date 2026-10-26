## ADDED Requirements

### Requirement: A gateway-backed agent run is attributed from the gateway's own records

When a gateway is configured and the runtime reaches its model through it, the
framework SHALL give each agent run a key of its own whose alias names the unit,
node and round, SHALL read that key's token and cost totals afterwards, SHALL record
them with source `gateway`, and SHALL revoke the key. Where no gateway is configured,
or the agent cannot take its key from its environment, the source SHALL be skipped
with a log line and the record SHALL fall back to the next source. A gateway failure
SHALL NOT fail a run.

#### Scenario: A run through the gateway

- **GIVEN** a configured gateway and an agent that takes its key from the environment
- **WHEN** a unit's implement step runs
- **THEN** the gateway's totals for that run's key are recorded with source `gateway`
- **AND** the key is revoked afterwards

#### Scenario: Concurrent units

- **WHEN** two units run agents at the same time
- **THEN** each unit's record holds only its own key's totals

#### Scenario: No gateway configured

- **WHEN** neither gateway setting is set
- **THEN** no key is minted and records use their other sources

#### Scenario: The gateway is down

- **GIVEN** a configured gateway that does not answer
- **WHEN** an agent run starts
- **THEN** the run proceeds, the record falls back and one warning is logged
