## From `abk-grafana-anonymous-push/1`

- In tests/cli/test_telemetry_push_dashboard.py, `test_a_refusal_with_a_token_does_not_blame_the_missing_token` checks `str(status) in text`. That check would also pass if the fake server's random port happened to contain "401" or "403". Asserting `f"HTTP Error {status}" in text` would pin the status without that chance.
