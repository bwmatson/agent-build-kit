# Tasks

Acceptance: none — a CLI command and package data; tier-1 tests with a fake
Grafana API prove it.

## 1. [agent-build-kit] [tier1] The dashboard lives here and is pushed

Needs: consumer-intake group 1 merged — the platform must accept pushed dashboards first

Done when `abk telemetry push-dashboard` pushes the framework's dashboard to a
configured Grafana, idempotently.

- [x] 1.1 Test: against a fake Grafana API, the command creates the folder if
      missing, posts the dashboard with overwrite, and a second run leaves one.
- [x] 1.2 Test: with no URL or token it names the missing setting and exits
      non-zero.
- [x] 1.3 Test: every metric name queried in the dashboard is one the telemetry
      module emits.
- [x] 1.4 Add the dashboard as package data, the command, and the three settings.
- [x] 1.5 Document it in `docs/configuration.md` and the `abk-config` skill, and
      add a changelog entry.
