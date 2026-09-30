# Category: Test coverage gaps

Weekly-cadence category (run via `recommend.md`) — a deliberate look at
where testing is thin in the one project this run is about, not a
routine check. Start from this project's own workspace (its root
`pyproject.toml` members, `package.json` workspaces, and its CI test
matrix) to see which members have a `tests/` directory at all — then
don't just restate that, go deeper:

- For the services/packages with zero tests, which ones are actually
  risky to leave untested? Weigh: does it handle auth/secrets (e.g. an
  API-key-gated internal route), does it sit on an
  externally-reachable route, has it had real bugs before (check git log
  for "fix"-flavored commits touching it), is its logic non-trivial
  (parsing, retry/backoff, state machines) vs. thin passthrough glue that
  barely needs a test. Rank a short list, don't just enumerate them all
  equally.
- For the services that DO have tests, is coverage concentrated on the
  easy/happy-path stuff while a genuinely risky code path (error
  handling, retry logic, an edge case the code itself comments on) has
  nothing? Spot-check one or two files per tested service rather than
  demanding exhaustive coverage analysis.
- Is there a *specific*, small, addable test that would meaningfully
  close a gap — e.g. one missing test for one already-identified risky
  function — as opposed to "this whole service needs a test suite" (too
  big for one task group)?

Report: a short prioritized list of untested/undertested areas with your
reasoning for the ranking, plus — separately — any single small,
bounded test addition specific enough for `propose.md` to actually
write up as a task group. Most findings here will be recommendations, not
actionable candidates; that's expected, say so plainly rather than
forcing everything into "actionable."
