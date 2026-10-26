## Why

The 20261026-125001 health run found the unit-test check failing on the base commit,
which parks every unit in `needs_person`. One of the seven failures is a test that
depends on the host: `tests/cli/test_telemetry_push_dashboard.py::test_without_a_url_it_names_the_setting_and_fails`
sets only `ABK_GRAFANA_TOKEN` and expects the missing-URL message, but fails on a host
whose environment already sets `ABK_GRAFANA_URL` (it then tries to connect to that URL).
The test must not assume the machine's environment.

## What Changes

- The test clears `ABK_GRAFANA_URL` from its environment before it runs, so it passes
  whatever the host sets.

## Not in this change

The other six failures are guards (`test_no_installation_leaks.py`, the docs guards,
`test_live_test_names.py`) flagging planning content under `openspec/` and `runs/`.
Whether to scrub that content or exempt it from the guards is a decision for a person,
so it is left out; see the run log.

## Capabilities

### New Capabilities
- `telemetry-dashboard-push`: the missing-URL behaviour holds regardless of the host environment.
