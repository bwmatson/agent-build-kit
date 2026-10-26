## From `an-internet-outage-is-not-a-failure/1`

- src/agent_build_kit/cli/pipeline.py:1833 — The `_sent_back` docstring still says only a unit 'parked for `host_unavailable`' is readmitted once its backoff has elapsed. The code now checks `unit.cause in PARKED_CAUSES`, which also covers `network_unavailable` and `service_unavailable`.
- src/agent_build_kit/pipeline/events.py:1512 — The reason for the deferral is picked with a chained conditional expression (`a if x else b if y else c`), which is harder to read than the two-way version it replaced.

## From `an-internet-outage-is-not-a-failure/2`

- Since review round 1, the claude_output.py fallback that reads the status from the CLI's words is `API Error: (?:\D{0,40}?)(\d{3})\b`. It now accepts up to 40 non-digits before the number, and no recorded CLI output confirms the 'Repeated 529 Overloaded errors' wording. When a real run records that text, add it as a fixture. If no run ever does, narrow the pattern back to known wordings.

## From `an-internet-outage-is-not-a-failure/3`

- When a network wait in plan_all marks the rest of the round's changes `skipped`, nothing is logged for them. A one-line log saying they were left for the tick that clears the network pause would make a tick's output easier to read during an outage.
- tests/pipeline/test_service_outage_restack.py still defines its own copy of the outage error text (`WORDS`). It could import it from tests/pipeline/test_network_outage_parking.py, as plan_outage_fakes.py now does, so the error wording lives in one place.
