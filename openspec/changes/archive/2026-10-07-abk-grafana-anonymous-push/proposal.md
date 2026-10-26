# Proposal

## Why

The dashboard push requires a Grafana URL and a token. A Grafana set up to allow anonymous Editor
access needs no token, and the platform the pipeline runs beside is set up that way
(`grafana-anonymous-editor`). Requiring a token the setup does not have blocks the push.

## What Changes

- **The token is optional.** With a URL and a token the push is exactly as today (a bearer token).
  With a URL and no token the request carries no authorization header.
- **A refusal is explained.** If the Grafana answers 401 or 403 on the token-less path, the command
  says that the Grafana at that URL does not allow anonymous Editor access and names
  `ABK_GRAFANA_TOKEN` as the fix. A missing URL still names `ABK_GRAFANA_URL`.
- **Doctor says which path is in use** (token or anonymous) when a URL is set.
- **The framework's documents** say the token is optional because whether an unauthenticated push is
  accepted depends on how the target Grafana is set up; the framework does not configure Grafana and
  names no installation. The statement that the shared stack's Grafana allows it belongs in that
  stack's own notes.
