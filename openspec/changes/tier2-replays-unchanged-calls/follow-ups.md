## From `tier2-replays-unchanged-calls/1`

- tests/replay/proxy.py `finish(passed=False)` now returns without waiting. A call still in flight then finishes after the staging directory has been removed, and it stages a file under the failed test's id. That file is never promoted, because `begin` clears that id's staging before a rerun. It does stay in the staging directory until then, so a short comment there would help the next reader.
- tests/replay/proxy.py `_forward` catches only `httpx.HTTPError`. `httpx.InvalidURL` (a malformed `upstreams[].url`) and `httpx.StreamError` do not subclass it. Either one still escapes the handler: the client sees the connection drop instead of a 502 that names the upstream. Validating `ReplayUpstream.url` when the config loads would cover the first.

## From `tier2-replays-unchanged-calls/2`

- Three small gaps that can wait. (1) No test covers the new early return in `tests/replay/plugin.py` `pytest_sessionfinish`, which makes an xdist worker skip counting runs and writing `report.json`. A pytester session with a `workerinput` attribute set on its config, asserting that `state.json` and `report.json` are left alone, would pin it. (2) No test covers the new exit code of `abk replay review --keep/--delete`, which is now 1 when no repository has a `tests.replay` section. (3) The line added to docs/agent-runtimes.md about `input_tokens`/`output_tokens` is not wrapped like the lines around it.
