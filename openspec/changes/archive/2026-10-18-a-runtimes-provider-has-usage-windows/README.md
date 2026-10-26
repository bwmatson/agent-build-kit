# a-runtimes-provider-has-usage-windows — a split's gate

The directory keeps its name because renaming it would orphan the stored units. The change is about **a split's gate**: a tier 2 split (a named subset of a repo's tier 2 tests, see
`tier2-splits-replace-runtime-tags`) may carry a `gate` in `abk.yaml`, and the gate holds the split when its provider's usage is over a threshold or when a command says it is not usable. A gate's
`provider` is a row of a small table in the kit (first row `modal`, with a monthly `budget_usd`) whose usage the pipeline reads through the provider's Python library, an optional kit extra
`modal` that includes the `acp` extra. The existing window limits (pause percent, ceiling, relief fraction, resume buffer) are accepted under the gate's provider and applied by the same
ramp code to the provider's billing month, so the split is usable below the threshold, held above it, and released gradually near the end of the month. The result is the same held-split state
`abk tier2 hold` writes, with `source: gate`, which lifts itself. A `gate.command` covers providers the table does not know. Readings are cached, unknown is never a pass, and `abk status` and
`abk doctor` show the numbers.
