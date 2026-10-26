# Design

Package data `telemetry/dashboards/pipeline.json`, queried metric names
asserted equal to the ones `telemetry.py` defines, so the two cannot drift. The
command reads `ABK_GRAFANA_URL`, `ABK_GRAFANA_TOKEN` and an optional
`ABK_GRAFANA_FOLDER` (default `agent-build-kit`) through settings; with no URL
it says what to set and exits non-zero. It creates the folder by uid if
missing and posts with `overwrite: true`.

The platform's copy (`logging/grafana-dashboards/pipeline.json` and its tests)
is removed by a task in the platform's repo once it is known to have merged.
