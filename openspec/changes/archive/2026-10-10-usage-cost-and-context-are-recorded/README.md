# usage-cost-and-context-are-recorded

Records each agent call's cost twice, as the call's own spend and as the session's running total, so every sum over cost
is right; repairs the existing ledger once with a temporary backfill command; and records how full the model's context
window was, per step and cumulatively, in tokens.
