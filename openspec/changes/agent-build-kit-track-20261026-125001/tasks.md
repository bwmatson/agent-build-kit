# Tasks

Acceptance: none — the change is to one unit test's environment; no consumer sees a new surface.

Priority: 1

## 1. [agent-build-kit] [unit-test] The missing-URL dashboard-push test clears the host's Grafana URL

Done when `test_without_a_url_it_names_the_setting_and_fails` passes with `ABK_GRAFANA_URL` set in the host environment. Estimate: about 15 changed lines.

- [ ] 1.1 Test: in `tests/cli/test_telemetry_push_dashboard.py`, a test sets `ABK_GRAFANA_URL` to a closed-port URL with `monkeypatch.setenv` and runs the missing-URL scenario, asserting the exit is non-zero and the output names `ABK_GRAFANA_URL`; it fails today because the push tries that URL.
- [ ] 1.2 Make `test_without_a_url_it_names_the_setting_and_fails` call `monkeypatch.delenv("ABK_GRAFANA_URL", raising=False)` before `reload(None)`, so 1.1 and the original test pass.
