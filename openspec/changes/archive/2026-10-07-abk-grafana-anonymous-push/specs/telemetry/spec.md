## MODIFIED Requirements

### Requirement: The pipeline's dashboard is the framework's and is pushed

The framework SHALL carry the dashboard for its own metrics, SHALL push it to a
Grafana named by settings on request, and SHALL name no installation. The
queries in the dashboard SHALL use the metric names the framework emits. The push
SHALL use a bearer token when one is set and SHALL send no credentials when none is, in
which case it relies on the target Grafana allowing an unauthenticated push.

#### Scenario: Pushing the dashboard

- **GIVEN** a Grafana URL, with or without a token, in settings
- **WHEN** `abk telemetry push-dashboard` runs twice
- **THEN** the dashboard exists once in the framework's folder

#### Scenario: No Grafana configured

- **WHEN** it runs with no URL set
- **THEN** it says which setting is missing and exits non-zero

#### Scenario: A renamed metric

- **WHEN** a metric the framework emits is renamed without the dashboard
- **THEN** a test fails

## ADDED Requirements

### Requirement: A refused unauthenticated push is explained

When a push sent with no credentials is refused with 401 or 403, the command SHALL say that
the Grafana does not allow an unauthenticated push and name the token setting as the fix, and
SHALL exit non-zero. Doctor SHALL say whether a configured Grafana is used with a token or
anonymously.

#### Scenario: Refused without a token

- **GIVEN** a Grafana that answers 401 to a request with no credentials
- **WHEN** the push runs with no token set
- **THEN** the message says anonymous access is not allowed there and names the token setting

#### Scenario: Doctor

- **GIVEN** a Grafana URL and no token
- **WHEN** doctor runs
- **THEN** it reports the Grafana as used anonymously
