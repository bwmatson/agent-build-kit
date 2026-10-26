# Proposal

## Why

`telemetry-intake` put a dashboard for the pipeline's metrics into the
platform's repository. A consumer's dashboard belongs with the consumer
(`consumer-intake`): the platform exposes Grafana's API and the consumer pushes.

## What Changes

- **The dashboard JSON lives in the framework**, as package data, next to the
  metric names it queries.
- **`abk telemetry push-dashboard`** pushes it to Grafana's API into a folder of
  its own, using a service-account token from settings. Idempotent.
- **Nothing installation-specific** is in the framework: the Grafana URL, token
  and folder come from settings.
- **The platform's copy is removed** if it has already merged.
