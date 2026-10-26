## ADDED Requirements

### Requirement: The pipeline's dashboard is the framework's and is pushed

The framework SHALL carry the dashboard for its own metrics, SHALL push it to a
Grafana named by settings on request, and SHALL name no installation. The
queries in the dashboard SHALL use the metric names the framework emits.

#### Scenario: Pushing the dashboard

- **GIVEN** a Grafana URL and token in settings
- **WHEN** `abk telemetry push-dashboard` runs twice
- **THEN** the dashboard exists once in the framework's folder

#### Scenario: No Grafana configured

- **WHEN** it runs with no URL set
- **THEN** it says which setting is missing and exits non-zero

#### Scenario: A renamed metric

- **WHEN** a metric the framework emits is renamed without the dashboard
- **THEN** a test fails
