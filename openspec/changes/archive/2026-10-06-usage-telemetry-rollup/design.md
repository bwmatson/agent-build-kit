# Design

The recorder that writes a ledger line also calls the telemetry meter with the same
figures minus the unit and change attributes, so there is one source and no second
accounting. Instruments: `abk.agent.cost`, `abk.agent.tokens` (already defined by
`abk-telemetry`; the cache split is added as a kind), `abk.wait.duration` (bucket
attribute), `abk.node.duration`. Source is an attribute so measured and estimated
series stay apart. The dashboard JSON is extended with panels for each and the same
test that asserts every queried metric exists applies.

Telemetry off: the meter is a no-op and the ledger is unchanged.
