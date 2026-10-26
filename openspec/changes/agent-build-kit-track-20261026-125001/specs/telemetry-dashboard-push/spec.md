## ADDED Requirements

### Requirement: The missing-URL test does not depend on the host environment

The test that a dashboard push without a Grafana URL names the setting and fails SHALL
clear `ABK_GRAFANA_URL` before it runs.

#### Scenario: The host sets a Grafana URL
- **GIVEN** the host environment sets `ABK_GRAFANA_URL`
- **WHEN** the missing-URL test runs
- **THEN** it passes, because the test removed the variable first
