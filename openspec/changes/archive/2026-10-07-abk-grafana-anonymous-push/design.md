# Design

## The request

`push-dashboard` builds its headers from the settings: `Content-Type` always, and
`Authorization: Bearer <token>` only when `grafana_token` is non-empty. The folder create and the
dashboard post use the same headers.

## Errors

A 401 or 403 with no token set raises a message of the form "<url> refused an unauthenticated push:
that Grafana does not allow anonymous Editor access; set ABK_GRAFANA_TOKEN to a service-account
token". With a token set the existing message is unchanged. A missing URL is reported as today.

## Doctor

When `grafana_url` is set, doctor prints `grafana: <url> (token)` or `grafana: <url> (anonymous)`;
with no URL it prints nothing about Grafana, as now.

## Documents

`docs/configuration.md` and the `abk-config` skill list `ABK_GRAFANA_TOKEN` as optional with the
sentence above; the architecture document's telemetry section and the changelog likewise. Nothing
in the framework names the platform's stack or says its Grafana is configured this way.

## Out of scope

Configuring Grafana; the platform change that enables anonymous access.
