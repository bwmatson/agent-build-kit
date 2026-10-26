# Tasks

Acceptance: none — metric instruments and dashboard panels; tier-1 tests with an
in-process receiver prove them.

## 1. [agent-build-kit] [tier1] Roll the ledger into metrics and the dashboard

Needs: usage-report group 1 merged — the shared reader and record shape
Needs: abk-pipeline-dashboard group 1 merged — the dashboard the panels extend

Done when the ledger's figures are exported with bounded attributes and the pipeline
dashboard shows them.

- [x] 1.1 Test: an agent record and a span record each add the expected instruments
      with only the bounded attributes; no unit id or change name appears on any metric.
- [x] 1.2 Test: measured and estimated sources are separate series, and with telemetry
      off nothing is exported.
- [x] 1.3 Test: every metric the extended dashboard queries is one the code emits.
- [x] 1.4 Add the instruments to the recorder's path and the panels to the dashboard.
- [x] 1.5 Document the instruments in `docs/architecture.md` and the changelog.
