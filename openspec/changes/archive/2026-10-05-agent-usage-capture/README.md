# agent-usage-capture

Keep what an agent call reports about its own cost: tokens by kind, dollars,
turns, duration and session. Write one record per call to an append-only ledger
under the state directory, tagged with the unit, node, round, role and model,
and with where the figures came from.
